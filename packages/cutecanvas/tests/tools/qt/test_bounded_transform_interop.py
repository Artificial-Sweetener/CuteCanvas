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

"""Mounted interoperability proof for bounded mappings and affine tools."""

from __future__ import annotations

import logging

from cutecanvas import (
    CuteCanvas,
    EditorTransformCommand,
    EditorTransformTarget,
    LayerPolicy,
)
from cutecanvas_test_support.harness.mounted_qpane import MountedQPaneHarness
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt
from PySide6.QtTest import QTest
from qpane.sdk.scene import BilinearLayerTransform, PiecewiseLayerTransform


def test_transform_shrinks_shared_edge_mapping_without_poisoning_scene(
    qapp,
    caplog,
) -> None:
    """A bounded edge edit remains renderable through a later affine gesture."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(400, 300),
        widget_size=QSize(800, 620),
        mask_count=2,
    )
    viewer = harness.viewer
    try:
        first_id, second_id = harness.mask_ids
        assert viewer.editor.coverage.rectangle(QRectF(0.0, 0.0, 200.0, 300.0))
        harness.activate_mask(1)
        assert viewer.editor.coverage.rectangle(QRectF(200.0, 0.0, 200.0, 300.0))
        harness.activate_mask(0)
        assert harness.wait_for_mask_render_idle()
        entries = {entry.mask_id: entry for entry in viewer.listMasksForComposition()}
        first = entries[first_id]
        second = entries[second_id]
        assert first.scene_id is not None and first.layer_id is not None
        assert second.layer_id is not None
        policy = LayerPolicy(selectable=True, movable=True, pixel_editable=True)
        viewer.setLayerInteractionPolicy(first.scene_id, first.layer_id, policy)
        viewer.setLayerInteractionPolicy(first.scene_id, second.layer_id, policy)
        assert viewer.setControlMode(viewer.CONTROL_MODE_SHARED_EDGE_RESIZE)

        _drag_scene(viewer, QPointF(200.0, 0.0), QPointF(50.0, 0.0))
        QTest.keyClick(viewer, Qt.Key_Return)
        harness.drain_events()
        bounded = viewer.layerTransform(first.scene_id, first.layer_id)
        assert isinstance(bounded, (PiecewiseLayerTransform, BilinearLayerTransform))
        source_boundary = bounded.source_boundary

        viewer.setSelectedLayer(first.scene_id, first.layer_id)
        assert viewer.selectedLayer().layer_id == first.layer_id
        assert viewer.setControlMode(viewer.CONTROL_MODE_TRANSFORM)
        harness.drain_events()
        interaction = viewer.sceneLayerTransformInteraction()
        box = interaction.presentation()
        assert box is not None
        start = next(
            point for handle, point in box.handles if handle.value == "bottom-right"
        )
        center = sum((point for _handle, point in box.handles), QPointF()) * (
            1.0 / len(box.handles)
        )
        finish = start + (center - start) * 0.2

        QTest.mousePress(viewer, Qt.LeftButton, Qt.NoModifier, start.toPoint())
        QTest.mouseMove(viewer, finish.toPoint(), delay=0)
        harness.drain_events()
        preview_scene = viewer.view().current_scene_descriptor()
        assert preview_scene is not None
        preview = next(
            layer.transform
            for layer in preview_scene.layers
            if layer.layer_id == first.layer_id
        )
        assert isinstance(preview, (PiecewiseLayerTransform, BilinearLayerTransform))
        assert preview.source_boundary == source_boundary

        QTest.mouseRelease(viewer, Qt.LeftButton, Qt.NoModifier, finish.toPoint())
        QTest.keyClick(viewer, Qt.Key_Return)
        harness.drain_events()
        committed = viewer.layerTransform(first.scene_id, first.layer_id)
        assert isinstance(committed, (PiecewiseLayerTransform, BilinearLayerTransform))
        assert committed.source_boundary == source_boundary
        assert not tuple(
            record for record in caplog.records if record.levelno >= logging.ERROR
        )
    finally:
        harness.close()


def test_transform_scales_a_shared_edge_triangle_without_tool_errors(
    qapp,
    caplog,
) -> None:
    """A shared-edge triangle remains directly transformable after commit."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(400, 300),
        widget_size=QSize(800, 620),
        mask_count=2,
    )
    viewer = harness.viewer
    try:
        first_id, second_id = harness.mask_ids
        assert viewer.editor.coverage.rectangle(QRectF(0.0, 0.0, 200.0, 300.0))
        harness.activate_mask(1)
        assert viewer.editor.coverage.rectangle(QRectF(200.0, 0.0, 200.0, 300.0))
        harness.activate_mask(0)
        assert harness.wait_for_mask_render_idle()
        entries = {entry.mask_id: entry for entry in viewer.listMasksForComposition()}
        first = entries[first_id]
        second = entries[second_id]
        assert first.scene_id is not None and first.layer_id is not None
        assert second.layer_id is not None
        policy = LayerPolicy(selectable=True, movable=True, pixel_editable=True)
        viewer.setLayerInteractionPolicy(first.scene_id, first.layer_id, policy)
        viewer.setLayerInteractionPolicy(first.scene_id, second.layer_id, policy)
        assert viewer.setControlMode(viewer.CONTROL_MODE_SHARED_EDGE_RESIZE)

        _drag_scene(viewer, QPointF(200.0, 0.0), QPointF(400.0, 0.0))
        _drag_scene(viewer, QPointF(200.0, 300.0), QPointF(0.0, 300.0))
        QTest.keyClick(viewer, Qt.Key_Return)
        harness.drain_events()
        triangle = viewer.layerTransform(first.scene_id, first.layer_id)
        assert isinstance(triangle, BilinearLayerTransform)

        viewer.setSelectedLayer(first.scene_id, first.layer_id)
        assert viewer.setControlMode(viewer.CONTROL_MODE_TRANSFORM)
        harness.drain_events()
        box = viewer.sceneLayerTransformInteraction().presentation()
        assert box is not None
        assert len(box.handles) == 8
        _assert_axis_aligned_transform_box(box.corners)
        start = next(
            point for handle, point in box.handles if handle.value == "top-left"
        )
        finish = start + QPointF(24.0, 18.0)
        QTest.mousePress(viewer, Qt.LeftButton, Qt.NoModifier, start.toPoint())
        QTest.mouseMove(viewer, finish.toPoint(), delay=0)
        harness.drain_events()

        preview_scene = viewer.view().current_scene_descriptor()
        assert preview_scene is not None
        preview = next(
            layer.transform
            for layer in preview_scene.layers
            if layer.layer_id == first.layer_id
        )
        assert isinstance(preview, BilinearLayerTransform)
        assert preview != triangle
        assert preview.source_boundary == triangle.source_boundary

        QTest.mouseRelease(viewer, Qt.LeftButton, Qt.NoModifier, finish.toPoint())
        QTest.keyClick(viewer, Qt.Key_Return)
        harness.drain_events()
        assert viewer.layerTransform(first.scene_id, first.layer_id) == preview
        assert not tuple(
            record for record in caplog.records if record.levelno >= logging.ERROR
        )
    finally:
        harness.close()


def test_transform_commands_use_provisional_history_before_one_durable_edit(
    qapp,
) -> None:
    """Affine commands must undo within the active transform before the document."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(400, 300),
        widget_size=QSize(800, 620),
        mask_count=1,
    )
    viewer = harness.viewer
    try:
        mask_id = harness.mask_ids[0]
        assert viewer.editor.coverage.rectangle(QRectF(40.0, 60.0, 120.0, 80.0))
        entry = next(
            item for item in viewer.listMasksForComposition() if item.mask_id == mask_id
        )
        assert entry.scene_id is not None and entry.layer_id is not None
        viewer.setLayerInteractionPolicy(
            entry.scene_id,
            entry.layer_id,
            LayerPolicy(selectable=True, movable=True, pixel_editable=True),
        )
        viewer.setSelectedLayer(entry.scene_id, entry.layer_id)
        assert viewer.activateEditorTransform(EditorTransformTarget.LAYER_CONTENT)
        assert viewer.applyEditorTransformCommand(
            EditorTransformCommand.ROTATE_RIGHT_90
        )
        first = _active_layer_mapping(viewer, entry.layer_id)
        assert viewer.applyEditorTransformCommand(
            EditorTransformCommand.FLIP_HORIZONTAL
        )
        second = _active_layer_mapping(viewer, entry.layer_id)
        assert first != second
        state = viewer.activeEditSession()
        assert state is not None and state.undo_depth == 2
        assert state.can_apply and state.can_cancel
        assert viewer.layerTransform(entry.scene_id, entry.layer_id).isIdentity()

        assert viewer.undoEditorEdit()
        assert _active_layer_mapping(viewer, entry.layer_id) == first
        assert viewer.redoEditorEdit()
        assert _active_layer_mapping(viewer, entry.layer_id) == second
        assert viewer.applyActiveEditSession()
        assert (
            viewer.layerTransform(entry.scene_id, entry.layer_id)
            == second.to_qtransform()
        )
        assert viewer.undoSceneEdit()
        assert viewer.layerTransform(entry.scene_id, entry.layer_id).isIdentity()
    finally:
        harness.close()


def test_transform_no_op_release_clears_direct_gesture_ownership(qapp) -> None:
    """A click-only handle gesture remains resolvable without claiming the pointer."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(400, 300),
        widget_size=QSize(800, 620),
        mask_count=1,
    )
    viewer = harness.viewer
    try:
        mask_id = harness.mask_ids[0]
        assert viewer.editor.coverage.rectangle(QRectF(40.0, 60.0, 120.0, 80.0))
        entry = next(
            item for item in viewer.listMasksForComposition() if item.mask_id == mask_id
        )
        assert entry.scene_id is not None and entry.layer_id is not None
        viewer.setLayerInteractionPolicy(
            entry.scene_id,
            entry.layer_id,
            LayerPolicy(selectable=True, movable=True, pixel_editable=True),
        )
        viewer.setSelectedLayer(entry.scene_id, entry.layer_id)
        assert viewer.setControlMode(viewer.CONTROL_MODE_TRANSFORM)
        box = viewer.sceneLayerTransformInteraction().presentation()
        assert box is not None
        handle = box.handles[0][1].toPoint()

        QTest.mousePress(viewer, Qt.LeftButton, Qt.NoModifier, handle)
        QTest.mouseRelease(viewer, Qt.LeftButton, Qt.NoModifier, handle)

        state = viewer.activeEditSession()
        assert state is not None
        assert not state.gesture_active
        assert not state.can_undo
        assert viewer.cancelActiveEditSession()
    finally:
        harness.close()


def _drag_scene(viewer: CuteCanvas, start: QPointF, finish: QPointF) -> None:
    """Complete one mounted scene-space pointer drag."""
    view = viewer.view()
    start_panel = view.scene_to_panel_point(start)
    finish_panel = view.scene_to_panel_point(finish)
    assert start_panel is not None and finish_panel is not None
    start_point = QPoint(round(start_panel.x()), round(start_panel.y()))
    finish_point = QPoint(round(finish_panel.x()), round(finish_panel.y()))
    QTest.mouseMove(viewer, start_point)
    QTest.mousePress(viewer, Qt.LeftButton, Qt.NoModifier, start_point)
    QTest.mouseMove(viewer, finish_point, delay=0)
    QTest.mouseRelease(viewer, Qt.LeftButton, Qt.NoModifier, finish_point)


def _assert_axis_aligned_transform_box(corners: tuple[QPointF, ...]) -> None:
    """Require an affine bounding box rather than retained polygon vertices."""
    top_left, top_right, bottom_right, bottom_left = corners
    assert top_left.y() == top_right.y()
    assert top_right.x() == bottom_right.x()
    assert bottom_right.y() == bottom_left.y()
    assert bottom_left.x() == top_left.x()


def _active_layer_mapping(viewer: CuteCanvas, layer_id: object):
    """Return one mapping from the preview-processed active scene."""
    scene = viewer.view().current_scene_descriptor()
    assert scene is not None
    return next(layer.transform for layer in scene.layers if layer.layer_id == layer_id)
