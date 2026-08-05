#    QPane + CuteCanvas - High-performance PySide6 rendering and editing
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

"""Mounted shared canvas-aperture behavior for retained coverage tools."""

from __future__ import annotations

import uuid

import numpy as np
import pytest
from cutecanvas.coverage import CoverageCombineMode, CoverageGeometryFactory
from cutecanvas.coverage.canvas_aperture import CoverageCanvasAperture
from cutecanvas.coverage.document import VectorCoverageItem
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QPainterPath
from PySide6.QtTest import QTest
from qpane.sdk.raster import qimage_to_numpy_argb32

from tests.harness.mounted_qpane import MountedQPaneHarness
from tests.harness.timing import average_interaction_latency_ms


@pytest.mark.parametrize(
    "mode_name",
    ("CONTROL_MODE_SELECT_RECTANGLE", "CONTROL_MODE_SELECT_ELLIPSE"),
)
def test_pixel_selection_preview_and_commit_share_canvas_aperture(
    qapp,
    mode_name: str,
) -> None:
    """Out-of-bounds selection geometry must remain clipped while still dragging."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(1000, 800),
        widget_size=QSize(1400, 900),
    )
    viewer = harness.viewer
    try:
        assert viewer.configureSnapping(enabled=False)
        viewer.setControlMode(getattr(viewer, mode_name))
        start = viewer.view().scene_to_panel_point(QPointF(-50.0, 100.0))
        endpoint = viewer.view().scene_to_panel_point(QPointF(300.0, 400.0))
        canvas_edge = viewer.view().scene_to_panel_point(QPointF(0.0, 250.0))
        assert start is not None and endpoint is not None
        assert canvas_edge is not None
        before = qimage_to_numpy_argb32(harness.capture())

        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start.toPoint())
        QTest.mouseMove(viewer, endpoint.toPoint(), delay=0)
        harness.drain_events()

        presented = qimage_to_numpy_argb32(harness.capture())
        changed = np.any(before != presented, axis=2)
        canvas_left = round(canvas_edge.x())
        assert not np.any(changed[:, : canvas_left - 3])
        assert np.any(changed[:, canvas_left : canvas_left + 4])

        active_tool = viewer._tools_manager.get_active_tool()
        preview = active_tool._coverage_item()
        assert preview is not None
        preview_left, _top, preview_width, _height = preview.geometry.local_bounds
        assert preview_left == pytest.approx(0.0, abs=0.001)
        assert preview_left + preview_width == pytest.approx(300.0, abs=1.0)

        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=endpoint.toPoint())
        harness.drain_events()
        settled = qimage_to_numpy_argb32(harness.capture())
        settled_changes = np.any(before != settled, axis=2)
        assert not np.any(settled_changes[:, : canvas_left - 3])
        assert np.any(settled_changes[:, canvas_left : canvas_left + 4])
        selection = viewer.pixelSelectionState()
        assert selection.bounds is not None
        assert selection.bounds.left() == 0
        assert selection.bounds.right() + 1 == pytest.approx(300.0, abs=1.0)
        committed_bounds = selection.bounds
        assert viewer.undoSceneEdit()
        assert not viewer.pixelSelectionState().has_selection
        assert viewer.redoSceneEdit()
        assert viewer.pixelSelectionState().bounds == committed_bounds
    finally:
        harness.close()


def test_pixel_lasso_preview_and_commit_share_canvas_aperture(qapp) -> None:
    """Lasso geometry must use the same clipping owner as geometric selections."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(1000, 800),
        widget_size=QSize(1400, 900),
    )
    viewer = harness.viewer
    try:
        viewer.setControlMode(viewer.CONTROL_MODE_SELECT_LASSO)
        scene_points = (
            QPointF(-50.0, 100.0),
            QPointF(300.0, 100.0),
            QPointF(300.0, 400.0),
            QPointF(-50.0, 400.0),
        )
        panel_points = tuple(
            viewer.view().scene_to_panel_point(point) for point in scene_points
        )
        assert all(point is not None for point in panel_points)
        concrete_points = tuple(
            point.toPoint() for point in panel_points if point is not None
        )

        QTest.mousePress(
            viewer,
            Qt.MouseButton.LeftButton,
            pos=concrete_points[0],
        )
        for point in concrete_points[1:]:
            QTest.mouseMove(viewer, point, delay=0)
        harness.drain_events()

        active_tool = viewer._tools_manager.get_active_tool()
        preview = active_tool._coverage_item()
        assert preview is not None
        preview_left, _top, preview_width, _height = preview.geometry.local_bounds
        assert preview_left == pytest.approx(0.0, abs=0.001)
        assert preview_left + preview_width == pytest.approx(300.0, abs=1.0)

        QTest.mouseRelease(
            viewer,
            Qt.MouseButton.LeftButton,
            pos=concrete_points[-1],
        )
        harness.drain_events()
        selection = viewer.pixelSelectionState()
        assert selection.bounds is not None
        assert selection.bounds.left() == 0
        assert selection.bounds.right() + 1 == pytest.approx(300.0, abs=1.0)
        committed_bounds = selection.bounds
        assert viewer.undoSceneEdit()
        assert not viewer.pixelSelectionState().has_selection
        assert viewer.redoSceneEdit()
        assert viewer.pixelSelectionState().bounds == committed_bounds
    finally:
        harness.close()


def test_inside_selection_drag_moves_boundaries_without_moving_mask_content(
    qapp,
) -> None:
    """Selection-tool translation must never enter the selected-pixel move path."""
    harness = MountedQPaneHarness(qapp)
    viewer = harness.viewer
    try:
        selection_start = viewer.view().scene_to_panel_point(QPointF(100.0, 100.0))
        selection_end = viewer.view().scene_to_panel_point(QPointF(220.0, 220.0))
        drag_start = viewer.view().scene_to_panel_point(QPointF(150.0, 150.0))
        drag_end = viewer.view().scene_to_panel_point(QPointF(190.0, 175.0))
        assert selection_start is not None and selection_end is not None
        assert drag_start is not None and drag_end is not None

        layer = viewer.mask_service.assets.get_layer(harness.mask_ids[0])
        assert layer is not None
        layer.coverage.raster.mutate(
            lambda pixels, _image: pixels[140:160, 140:160].fill(255)
        )
        content_before = layer.coverage.raster.snapshot_array()
        assert content_before.any()

        viewer.setControlMode(viewer.CONTROL_MODE_SELECT_RECTANGLE)
        QTest.mousePress(
            viewer,
            Qt.MouseButton.LeftButton,
            pos=selection_start.toPoint(),
        )
        QTest.mouseMove(viewer, selection_end.toPoint(), delay=0)
        QTest.mouseRelease(
            viewer,
            Qt.MouseButton.LeftButton,
            pos=selection_end.toPoint(),
        )
        harness.drain_events()
        before = viewer.pixelSelectionState()
        assert before is not None and before.bounds is not None

        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=drag_start.toPoint())
        QTest.mouseMove(viewer, drag_end.toPoint(), delay=0)
        preview = viewer.pixelSelectionState()
        assert preview is not None and preview.bounds is not None
        assert preview.bounds != before.bounds
        np.testing.assert_array_equal(
            layer.coverage.raster.snapshot_array(),
            content_before,
        )
        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=drag_end.toPoint())
        harness.drain_events()

        moved = viewer.pixelSelectionState()
        assert moved is not None and moved.bounds is not None
        assert moved.bounds.x() - before.bounds.x() == 40
        assert moved.bounds.y() - before.bounds.y() == 25
        np.testing.assert_array_equal(
            layer.coverage.raster.snapshot_array(),
            content_before,
        )
        assert viewer.undoSceneEdit()
        assert viewer.pixelSelectionState().bounds == before.bounds
        np.testing.assert_array_equal(
            layer.coverage.raster.snapshot_array(),
            content_before,
        )
    finally:
        harness.close()


def test_out_of_bounds_selection_input_storm_stays_clipped_and_cancelable(
    qapp,
) -> None:
    """Hostile edge reversals must not leak geometry or survive cancellation."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(1000, 800),
        widget_size=QSize(1400, 900),
    )
    viewer = harness.viewer
    try:
        assert viewer.configureSnapping(enabled=False)
        viewer.setControlMode(viewer.CONTROL_MODE_SELECT_RECTANGLE)
        start = viewer.view().scene_to_panel_point(QPointF(-200.0, 100.0))
        left_endpoint = viewer.view().scene_to_panel_point(QPointF(-100.0, 700.0))
        right_endpoint = viewer.view().scene_to_panel_point(QPointF(1200.0, 700.0))
        assert start is not None and left_endpoint is not None
        assert right_endpoint is not None

        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start.toPoint())
        active_tool = viewer._tools_manager.get_active_tool()
        for index in range(200):
            endpoint = left_endpoint if index % 2 else right_endpoint
            QTest.mouseMove(viewer, endpoint.toPoint(), delay=0)
            preview = active_tool._coverage_item()
            if index % 2:
                assert preview is None
                continue
            assert preview is not None
            left, _top, width, _height = preview.geometry.local_bounds
            assert left == pytest.approx(0.0)
            assert left + width == pytest.approx(1000.0)

        QTest.keyClick(viewer, Qt.Key.Key_Escape)
        harness.drain_events()
        assert not viewer.pixelSelectionState().has_selection
        assert active_tool._coverage_item() is None
    finally:
        harness.close()


@pytest.mark.interactive_performance
def test_inside_canvas_coverage_constraint_retains_bounded_pointer_cost() -> None:
    """The common fully-inside fast path must stay cheap during input storms."""
    path = QPainterPath()
    path.addRect(0.0, 0.0, 16_384.0, 16_384.0)
    aperture = CoverageCanvasAperture(
        active_scene=lambda: None,
        panel_to_scene=lambda point: QPointF(point),
        target_to_panel=lambda point: QPointF(point),
        target_aperture_path=lambda: path,
    )
    item = VectorCoverageItem(
        item_id=uuid.uuid4(),
        geometry=CoverageGeometryFactory().rectangle(QRectF(20.0, 40.0, 80.0, 60.0)),
        combine_mode=CoverageCombineMode.ADD,
    )

    latency_ms = average_interaction_latency_ms(
        lambda: aperture.constrain_item(item),
        repetitions=10_000,
    )

    assert latency_ms < 0.02
