#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Public editing contract tests for color raster scene layers."""

from __future__ import annotations

import time
import uuid

from PySide6.QtCore import QRect, QRectF
from PySide6.QtGui import QColor, QImage

from qpane import QPaneLayerInteractionPolicy
from qpane.scene.render_plan import RasterLayerRenderItem

pytest_plugins = ("tests.test_mask_workflows",)


def _opaque_image(width: int, height: int) -> QImage:
    """Return an opaque premultiplied color raster."""
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(40, 120, 220, 255))
    return image


def test_editable_raster_deletes_soft_selection_and_undoes_chronologically(
    qpane_with_mask,
) -> None:
    """Selection delete should preserve unselected color and restore with scene undo."""
    qpane, _manager, _image_id = qpane_with_mask
    scene = qpane.currentScene()
    assert scene is not None
    layer_id = qpane.addEditableRasterLayer(
        _opaque_image(8, 8),
        placement=QRectF(0.0, 0.0, 8.0, 8.0),
        label="Paint",
    )
    assert layer_id is not None
    updated_scene = qpane.currentScene()
    assert updated_scene is not None
    public_layer = next(
        layer for layer in updated_scene.layers if layer.layer_id == layer_id
    )
    assert public_layer.source_kind == "raster"
    assert public_layer.source_id is not None
    assert public_layer.image_id is None
    assert qpane.setSelectedLayer(scene.scene_id, layer_id)
    coverage = QImage(4, 8, QImage.Format_Grayscale8)
    coverage.fill(128)
    assert qpane.setPixelSelection(coverage, QRect(0, 0, 4, 8))

    assert qpane.deleteSelectedPixels()
    edited = qpane.editableRasterLayerImage(scene.scene_id, layer_id)
    assert edited is not None
    assert 126 <= edited.pixelColor(1, 1).alpha() <= 128
    assert edited.pixelColor(6, 1).alpha() == 255

    assert qpane.undoSceneEdit()
    restored = qpane.editableRasterLayerImage(scene.scene_id, layer_id)
    assert restored is not None
    assert restored.pixelColor(1, 1).alpha() == 255

    assert qpane.redoSceneEdit()
    redone = qpane.editableRasterLayerImage(scene.scene_id, layer_id)
    assert redone is not None
    assert 126 <= redone.pixelColor(1, 1).alpha() <= 128


def test_editable_raster_delete_projects_through_scaled_offset_bounds(
    qapp,
    qpane_with_mask,
) -> None:
    """RGBA deletion must share exact scene-to-local projection with masks."""
    qpane, _manager, _image_id = qpane_with_mask
    scene = qpane.currentScene()
    assert scene is not None
    layer_id = qpane.addEditableRasterLayer(
        _opaque_image(8, 8),
        interaction=QPaneLayerInteractionPolicy(
            selectable=True,
            movable=True,
            pixel_editable=True,
        ),
    )
    assert layer_id is not None
    completion: list[tuple[object, ...]] = []
    qpane.rasterBoundsRequestCompleted.connect(
        lambda *values: completion.append(tuple(values))
    )
    request_id = qpane.requestRasterBounds(
        scene.scene_id,
        layer_id,
        QRect(-2, -1, 12, 10),
    )
    assert request_id is not None
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and not completion:
        qapp.processEvents()
        time.sleep(0.005)
    assert completion
    assert completion[-1][3] is True
    assert qpane.setLayerPlacement(
        scene.scene_id,
        layer_id,
        QRectF(10.0, 20.0, 24.0, 20.0),
    )
    assert qpane.setSelectedLayer(scene.scene_id, layer_id)
    coverage = QImage(8, 8, QImage.Format_Grayscale8)
    coverage.fill(128)
    assert qpane.setPixelSelection(coverage, QRect(14, 24, 8, 8))
    before = qpane.editableRasterLayerImage(scene.scene_id, layer_id)
    assert before is not None

    assert qpane.deleteSelectedPixels()
    after = qpane.editableRasterLayerImage(scene.scene_id, layer_id)
    assert after is not None
    for y in range(after.height()):
        for x in range(after.width()):
            expected = before.pixelColor(x, y).alpha()
            if 2 <= x < 6 and 2 <= y < 6:
                expected = (expected * 127 + 127) // 255
            assert after.pixelColor(x, y).alpha() == expected
    assert qpane.undoSceneEdit()
    restored = qpane.editableRasterLayerImage(scene.scene_id, layer_id)
    assert restored == before
    assert qpane.redoSceneEdit()
    redone = qpane.editableRasterLayerImage(scene.scene_id, layer_id)
    assert redone == after


def test_catalog_image_remains_frozen_without_editable_capability(
    qpane_with_mask,
) -> None:
    """A host policy cannot grant pixel editing to an intrinsically frozen source."""
    qpane, _manager, _image_id = qpane_with_mask
    scene = qpane.currentScene()
    assert scene is not None
    base = scene.layers[0]
    assert qpane.setLayerInteractionPolicy(
        scene.scene_id,
        base.layer_id,
        QPaneLayerInteractionPolicy(selectable=True, pixel_editable=True),
    )
    assert qpane.setSelectedLayer(scene.scene_id, base.layer_id)
    assert qpane.selectAllPixels()
    assert not qpane.deleteSelectedPixels()


def test_editable_raster_bounds_are_async_and_undoable(qapp, qpane_with_mask) -> None:
    """RGBA bounds work should complete off-thread and join scene chronology."""
    qpane, _manager, _image_id = qpane_with_mask
    scene = qpane.currentScene()
    assert scene is not None
    layer_id = qpane.addEditableRasterLayer(_opaque_image(8, 8), label="Paint")
    assert layer_id is not None
    requested = QRect(-2, -3, 12, 14)

    request_id = qpane.requestRasterBounds(scene.scene_id, layer_id, requested)

    assert request_id is not None
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        qapp.processEvents()
        state = qpane.rasterSurfaceState(scene.scene_id, layer_id)
        if state is not None and state.pending_request_id is None:
            break
        time.sleep(0.005)
    state = qpane.rasterSurfaceState(scene.scene_id, layer_id)
    assert state is not None
    assert state.bounds == requested
    assert qpane.undoSceneEdit()
    restored = qpane.rasterSurfaceState(scene.scene_id, layer_id)
    assert restored is not None
    assert restored.bounds == QRect(0, 0, 8, 8)
    assert qpane.redoSceneEdit()
    redone = qpane.rasterSurfaceState(scene.scene_id, layer_id)
    assert redone is not None
    assert redone.bounds == requested


def test_editable_raster_assets_are_pruned_with_catalog_scene(qpane_with_mask) -> None:
    """Removing catalog scenes should not retain orphaned RGBA authoring assets."""
    qpane, _manager, _image_id = qpane_with_mask
    layer_id = qpane.addEditableRasterLayer(_opaque_image(8, 8), label="Paint")
    assert layer_id is not None
    scene = qpane.currentScene()
    assert scene is not None
    layer = next(
        candidate for candidate in scene.layers if candidate.layer_id == layer_id
    )
    assert layer.source_id is not None
    assert qpane._editable_raster_assets.get(layer.source_id) is not None

    qpane.clearImages()

    assert qpane._editable_raster_assets.get(layer.source_id) is None


def test_editable_raster_participates_in_normal_render_plan(qpane_with_mask) -> None:
    """Composition-owned RGBA layers must use the established raster pipeline."""
    qpane, _manager, _image_id = qpane_with_mask
    layer_id = qpane.addEditableRasterLayer(
        _opaque_image(32, 24),
        placement=QRectF(0.0, 0.0, 8.0, 8.0),
        label="Rendered paint",
    )
    assert layer_id is not None

    plan = qpane.view().calculateRenderPlan(is_blank=False)

    assert plan is not None
    item = next(
        candidate
        for candidate in plan.render_items
        if candidate.descriptor.layer_id == layer_id
    )
    assert isinstance(item, RasterLayerRenderItem)
    assert item.descriptor.label == "Rendered paint"


def test_shared_editable_raster_instances_edit_together_but_place_independently(
    qpane_with_mask,
) -> None:
    """A shared raster source must not collapse independent layer presentation."""
    qpane, _manager, _image_id = qpane_with_mask
    scene = qpane.currentScene()
    composition_id = qpane.currentCompositionID()
    assert scene is not None
    assert composition_id is not None
    original_id = qpane.addEditableRasterLayer(
        _opaque_image(8, 8),
        placement=QRectF(0.0, 0.0, 8.0, 8.0),
        interaction=QPaneLayerInteractionPolicy(
            selectable=True,
            movable=True,
            pixel_editable=True,
        ),
        label="Shared paint",
    )
    assert original_id is not None
    store = qpane.compositionService().layers
    original_instance = store.layer(composition_id, original_id)
    assert original_instance is not None
    duplicate_id = uuid.uuid4()
    duplicate = store.duplicate_layer(
        composition_id,
        original_id,
        duplicate_id,
        transform=original_instance.transform.translated(16.0, 0.0),
    )
    assert duplicate is not None
    qpane.view().invalidate_content_cache()

    original_before = qpane.editableRasterLayerImage(scene.scene_id, original_id)
    duplicate_before = qpane.editableRasterLayerImage(scene.scene_id, duplicate_id)
    assert original_before == duplicate_before
    assert qpane.setSelectedLayer(scene.scene_id, original_id)
    selection = QImage(1, 1, QImage.Format_Grayscale8)
    selection.fill(128)
    assert qpane.setPixelSelection(selection, QRect(0, 0, 1, 1))
    assert qpane.deleteSelectedPixels()
    assert qpane.editableRasterLayerImage(
        scene.scene_id, original_id
    ) == qpane.editableRasterLayerImage(scene.scene_id, duplicate_id)

    assert qpane.setLayerPlacement(
        scene.scene_id,
        duplicate_id,
        QRectF(4.0, 0.0, 4.0, 8.0),
    )
    moved = qpane.currentScene()
    assert moved is not None
    placements = {layer.layer_id: layer.placement for layer in moved.layers}
    assert placements[original_id] == QRectF(0.0, 0.0, 8.0, 8.0)
    assert placements[duplicate_id] == QRectF(4.0, 0.0, 4.0, 8.0)
    plan = qpane.view().calculateRenderPlan(is_blank=False)
    assert plan is not None
    shared_items = [
        item
        for item in plan.render_items
        if item.descriptor.layer_id in {original_id, duplicate_id}
    ]
    assert len(shared_items) == 2
    assert shared_items[0].asset_key != shared_items[1].asset_key
    assert shared_items[0].pyramid_asset_key == shared_items[1].pyramid_asset_key
    assert qpane.undoSceneEdit()
    restored = qpane.currentScene()
    assert restored is not None
    restored_placements = {layer.layer_id: layer.placement for layer in restored.layers}
    assert restored_placements[duplicate_id] == QRectF(16.0, 0.0, 8.0, 8.0)

    source_id = original_instance.source.resource_id
    assert store.remove_layer(composition_id, duplicate_id)
    assert qpane._editable_raster_assets.get(source_id) is not None
    assert store.remove_layer(composition_id, original_id)
    assert qpane._editable_raster_assets.get(source_id) is not None
    qpane.compositionService().edit_history.clear_scope(composition_id)
    assert qpane._editable_raster_assets.get(source_id) is None
