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

from cutecanvas import CuteCanvas, LayerPolicy
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
