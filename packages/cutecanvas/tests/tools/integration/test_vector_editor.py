#    CuteCanvas - High-performance layered image editor
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""Public and domain integration tests for semantic vector layers."""

from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRectF, QSize
from PySide6.QtGui import QColor, QTransform

from cutecanvas import (
    VectorFillRule,
    VectorPathCommand,
    VectorPathCommandKind,
    VectorShapeKind,
    VectorStyle,
)
from qpane.scene.render_plan import RasterLayerRenderItem, VectorLayerRenderItem


def test_vector_layer_renders_semantic_shapes_and_replays_history(
    qpane_with_mask,
) -> None:
    """Parametric shapes should render and undo without rasterizing authority."""
    qpane, _manager, _image_id = qpane_with_mask
    scene = qpane.currentScene()
    assert scene is not None

    layer_id = qpane.createVectorLayer(QSize(128, 96), label="Artwork")
    assert layer_id is not None
    object_id = qpane.addVectorShape(
        scene.scene_id,
        layer_id,
        VectorShapeKind.ELLIPSE,
        QRectF(16.0, 12.0, 64.0, 48.0),
        VectorStyle(
            fill=QColor(0, 220, 160, 180),
            stroke=QColor(255, 255, 255),
            stroke_width=3.0,
        ),
    )
    assert object_id is not None
    state = qpane.vectorDocumentState(scene.scene_id, layer_id)
    assert state is not None
    assert state.revision == 1
    assert state.objects[0].shape_kind is VectorShapeKind.ELLIPSE
    public_scene = qpane.currentScene()
    assert public_scene is not None
    public_layer = next(
        layer for layer in public_scene.layers if layer.layer_id == layer_id
    )
    assert public_layer.source_kind == "vector"

    plan = qpane.view().presenter.calculateRenderPlan()
    assert plan is not None
    vector_item = next(
        item for item in plan.render_items if isinstance(item, VectorLayerRenderItem)
    )
    assert vector_item.descriptor.layer_id == layer_id
    assert not vector_item.picture.isNull()

    assert qpane.undoSceneEdit()
    undone = qpane.vectorDocumentState(scene.scene_id, layer_id)
    assert undone is not None and undone.objects == ()
    assert qpane.redoSceneEdit()
    redone = qpane.vectorDocumentState(scene.scene_id, layer_id)
    assert redone is not None and redone.objects[0].object_id == object_id


def test_vector_layer_content_bounds_include_visible_stroke(qpane_with_mask) -> None:
    """Manipulation geometry must match the pixels painted by a vector layer."""
    qpane, _manager, _image_id = qpane_with_mask
    scene = qpane.currentScene()
    assert scene is not None
    layer_id = qpane.createVectorLayer(QSize(128, 96), label="Stroked bounds")
    assert layer_id is not None
    assert qpane.addVectorShape(
        scene.scene_id,
        layer_id,
        VectorShapeKind.RECTANGLE,
        QRectF(10.0, 12.0, 60.0, 40.0),
        VectorStyle(
            fill=QColor("white"),
            stroke=QColor("blue"),
            stroke_width=8.0,
        ),
    )

    assert qpane.layerLocalBounds(scene.scene_id, layer_id) == QRectF(
        6.0,
        8.0,
        68.0,
        48.0,
    )


def test_vector_path_selection_and_updates_remain_independent(
    qpane_with_mask,
) -> None:
    """Object selection should not replace scene-space pixel selection."""
    qpane, _manager, _image_id = qpane_with_mask
    scene = qpane.currentScene()
    assert scene is not None
    layer_id = qpane.createVectorLayer(label="Paths")
    assert layer_id is not None
    commands = (
        VectorPathCommand(VectorPathCommandKind.MOVE, (QPointF(10.0, 10.0),)),
        VectorPathCommand(VectorPathCommandKind.LINE, (QPointF(80.0, 10.0),)),
        VectorPathCommand(VectorPathCommandKind.LINE, (QPointF(45.0, 70.0),)),
        VectorPathCommand(VectorPathCommandKind.CLOSE),
    )
    object_id = qpane.addVectorPath(
        scene.scene_id,
        layer_id,
        commands,
        VectorStyle(fill_rule=VectorFillRule.EVEN_ODD),
    )
    assert object_id is not None
    assert qpane.setSelectedVectorObjects(scene.scene_id, layer_id, (object_id,))
    vector_selection = qpane.vectorSelectionState()
    assert vector_selection is not None
    assert vector_selection.object_ids == (object_id,)
    pixel_selection = qpane.pixelSelectionState()
    assert pixel_selection is not None and not pixel_selection.has_selection

    transform = QTransform()
    transform.translate(12.5, -4.0)
    transform.rotate(22.0)
    assert qpane.updateVectorObject(
        scene.scene_id,
        layer_id,
        object_id,
        transform=transform,
    )
    updated = qpane.vectorDocumentState(scene.scene_id, layer_id)
    assert updated is not None
    assert updated.objects[0].transform == transform
    assert qpane.clearVectorSelection()
    assert qpane.vectorSelectionState() is None


def _wait_for_vector_request(qapp, completions: list[tuple], request_id) -> tuple:
    """Pump queued worker delivery until one vector request terminates."""
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        qapp.processEvents()
        matching = [item for item in completions if item[0] == request_id]
        if matching:
            return matching[-1]
        time.sleep(0.002)
    raise AssertionError("vector request did not complete")


def test_vector_conversions_use_selection_and_raster_authorities_atomically(
    qapp,
    qpane_with_mask,
) -> None:
    """Vector derivatives should commit once and retain exact undoable geometry."""
    qpane, _manager, _image_id = qpane_with_mask
    scene = qpane.currentScene()
    assert scene is not None
    layer_id = qpane.createVectorLayer(QSize(120, 90), label="Convertible")
    assert layer_id is not None
    object_id = qpane.addVectorShape(
        scene.scene_id,
        layer_id,
        VectorShapeKind.RECTANGLE,
        QRectF(10.0, 12.0, 60.0, 40.0),
        VectorStyle(
            fill=QColor(20, 180, 240, 128),
            stroke=None,
        ),
    )
    assert object_id is not None
    completions: list[tuple] = []
    qpane.vectorRequestCompleted.connect(
        lambda *values: completions.append(tuple(values))
    )

    selection_request = qpane.convertVectorToPixelSelection(
        scene.scene_id,
        layer_id,
        (object_id,),
    )
    assert selection_request is not None
    selection_completion = _wait_for_vector_request(
        qapp,
        completions,
        selection_request,
    )
    assert selection_completion[3:] == ("pixel-selection", True, "")
    selection = qpane.pixelSelectionState()
    assert selection is not None and selection.has_selection
    assert selection.bounds == QRectF(10.0, 12.0, 60.0, 40.0).toRect()
    assert qpane.undoSceneEdit()
    assert not qpane.pixelSelectionState().has_selection
    assert qpane.redoSceneEdit()
    assert qpane.pixelSelectionState().has_selection

    before = next(
        item for item in qpane.currentScene().layers if item.layer_id == layer_id
    )
    raster_request = qpane.rasterizeLayer(
        scene.scene_id,
        layer_id,
        QSize(240, 180),
    )
    assert raster_request is not None
    raster_completion = _wait_for_vector_request(qapp, completions, raster_request)
    assert raster_completion[3:] == ("editable-raster", True, "")
    raster_layer = next(
        item for item in qpane.currentScene().layers if item.layer_id == layer_id
    )
    assert raster_layer.source_kind == "raster"
    assert raster_layer.placement == before.placement
    raster = qpane.editableRasterLayerImage(scene.scene_id, layer_id)
    assert raster is not None and raster.size() == QSize(240, 180)
    assert raster.pixelColor(80, 64).alpha() == 128

    assert qpane.undoSceneEdit()
    restored = next(
        item for item in qpane.currentScene().layers if item.layer_id == layer_id
    )
    assert restored.source_kind == "vector"
    assert restored.placement == before.placement
    assert qpane.redoSceneEdit()
    assert (
        next(
            item for item in qpane.currentScene().layers if item.layer_id == layer_id
        ).source_kind
        == "raster"
    )


def test_vector_layer_promotes_to_editable_mask_and_replays_as_one_stack_edit(
    qapp,
    qpane_with_mask,
) -> None:
    """Vector masks should clip any layer while retaining semantic edit authority."""
    qpane, _manager, _image_id = qpane_with_mask
    scene = qpane.currentScene()
    assert scene is not None
    base = scene.layers[0]
    vector_layer_id = qpane.createVectorLayer(QSize(400, 400), label="Mask path")
    assert vector_layer_id is not None
    object_id = qpane.addVectorShape(
        scene.scene_id,
        vector_layer_id,
        VectorShapeKind.RECTANGLE,
        QRectF(0.0, 0.0, 180.0, 400.0),
        VectorStyle(fill=QColor("white"), stroke=None),
    )
    assert object_id is not None

    assert qpane.setVectorMask(
        scene.scene_id,
        vector_layer_id,
        base.layer_id,
        (object_id,),
    )
    masked_scene = qpane.currentScene()
    assert masked_scene is not None
    assert all(layer.layer_id != vector_layer_id for layer in masked_scene.layers)
    state = qpane.vectorMaskState(scene.scene_id, base.layer_id)
    assert state is not None
    assert state.object_ids == (object_id,)
    document = qpane.vectorDocumentState(scene.scene_id, base.layer_id)
    assert document is not None and document.vector_id == state.vector_id

    plan = qpane.view().calculateRenderPlan()
    assert plan is not None
    base_item = next(
        item
        for item in plan.render_items
        if isinstance(item, RasterLayerRenderItem)
        and item.descriptor.layer_id == base.layer_id
    )
    assert base_item.effect_clip_path is not None
    assert base_item.effect_clip_path.contains(QPointF(100.0, 100.0))
    assert not base_item.effect_clip_path.contains(QPointF(300.0, 100.0))

    moved = QTransform()
    moved.translate(100.0, 0.0)
    assert qpane.updateVectorObject(
        scene.scene_id,
        base.layer_id,
        object_id,
        transform=moved,
    )
    updated_plan = qpane.view().calculateRenderPlan()
    updated_base = next(
        item
        for item in updated_plan.render_items
        if isinstance(item, RasterLayerRenderItem)
        and item.descriptor.layer_id == base.layer_id
    )
    assert not updated_base.effect_clip_path.contains(QPointF(50.0, 100.0))
    assert updated_base.effect_clip_path.contains(QPointF(200.0, 100.0))

    completions: list[tuple] = []
    qpane.vectorRequestCompleted.connect(
        lambda *values: completions.append(tuple(values))
    )
    request_id = qpane.convertVectorToPixelSelection(
        scene.scene_id,
        base.layer_id,
    )
    assert request_id is not None
    assert _wait_for_vector_request(qapp, completions, request_id)[4] is True
    assert qpane.pixelSelectionState().has_selection

    assert qpane.undoSceneEdit()
    assert not qpane.pixelSelectionState().has_selection
    assert qpane.undoSceneEdit()
    assert qpane.vectorMaskState(scene.scene_id, base.layer_id) is not None
    assert qpane.undoSceneEdit()
    restored_scene = qpane.currentScene()
    assert restored_scene is not None
    assert any(layer.layer_id == vector_layer_id for layer in restored_scene.layers)
    assert qpane.vectorMaskState(scene.scene_id, base.layer_id) is None
    assert qpane.redoSceneEdit()
    assert qpane.vectorMaskState(scene.scene_id, base.layer_id) is not None
    assert qpane.clearVectorMask(scene.scene_id, base.layer_id)
    assert qpane.vectorMaskState(scene.scene_id, base.layer_id) is None


def test_vector_mask_subset_stays_empty_when_its_object_is_removed(
    qpane_with_mask,
) -> None:
    """Removing a referenced object must not reinterpret its subset as all objects."""
    qpane, _manager, _image_id = qpane_with_mask
    scene = qpane.currentScene()
    assert scene is not None
    base = scene.layers[0]
    vector_layer_id = qpane.createVectorLayer(QSize(400, 400))
    assert vector_layer_id is not None
    selected_id = qpane.addVectorShape(
        scene.scene_id,
        vector_layer_id,
        VectorShapeKind.RECTANGLE,
        QRectF(0.0, 0.0, 100.0, 100.0),
    )
    retained_id = qpane.addVectorShape(
        scene.scene_id,
        vector_layer_id,
        VectorShapeKind.ELLIPSE,
        QRectF(200.0, 200.0, 100.0, 100.0),
    )
    assert selected_id is not None and retained_id is not None
    assert qpane.setVectorMask(
        scene.scene_id,
        vector_layer_id,
        base.layer_id,
        (selected_id,),
    )
    assert qpane.removeVectorObject(scene.scene_id, base.layer_id, selected_id)
    plan = qpane.view().calculateRenderPlan()
    item = next(
        candidate
        for candidate in plan.render_items
        if candidate.descriptor.layer_id == base.layer_id
    )
    assert item.effect_clip_path is not None
    assert item.effect_clip_path.isEmpty()
    assert qpane.undoSceneEdit()
    restored = qpane.view().calculateRenderPlan()
    restored_item = next(
        candidate
        for candidate in restored.render_items
        if candidate.descriptor.layer_id == base.layer_id
    )
    assert restored_item.effect_clip_path is not None
    assert restored_item.effect_clip_path.contains(QPointF(50.0, 50.0))
    assert not restored_item.effect_clip_path.contains(QPointF(250.0, 250.0))
