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

"""Mounted editor proof for polygon selection and mask authoring."""

from __future__ import annotations

from cutecanvas.coverage import VectorCoverageItem
from cutecanvas_test_support.harness.mounted_qpane import MountedQPaneHarness
from PySide6.QtCore import QPoint, QPointF, QSize, Qt
from PySide6.QtTest import QTest


def test_polygon_selection_commits_one_retained_edit_with_undo_redo(qapp) -> None:
    """Point-by-point selection authors one retained item and history command."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(400, 300),
        widget_size=QSize(800, 620),
    )
    viewer = harness.viewer
    try:
        assert viewer.setControlMode(viewer.CONTROL_MODE_SELECT_POLYGON)
        _click_polygon(viewer, _polygon_points(viewer))
        QTest.keyClick(viewer, Qt.Key.Key_Return)
        harness.drain_events()

        state = viewer.pixelSelectionState()
        assert state is not None and state.has_selection
        scene_id = state.scene_id
        document = viewer._pixel_selection.document(scene_id)
        assert document is not None and len(document.items) == 1
        assert isinstance(document.items[0], VectorCoverageItem)
        bounds = state.bounds
        assert viewer.undoSceneEdit()
        assert not viewer.pixelSelectionState().has_selection
        assert viewer.redoSceneEdit()
        assert viewer.pixelSelectionState().bounds == bounds
    finally:
        harness.close()


def test_polygon_mask_preserves_existing_raster_coverage_and_retained_history(
    qapp,
) -> None:
    """Polygon authoring adds retained coverage without flattening raster pixels."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(400, 300),
        widget_size=QSize(800, 620),
        brush_size=24,
    )
    viewer = harness.viewer
    mask_id = harness.mask_ids[0]
    try:
        assert viewer.setControlMode(viewer.CONTROL_MODE_DRAW_BRUSH)
        QTest.mouseClick(viewer, Qt.MouseButton.LeftButton, pos=_panel(viewer, 50, 50))
        assert harness.wait_for_mask_undo_depth(mask_id, 1)
        assert harness.wait_for_mask_render_idle()
        layer = viewer.mask_service.assets.get_layer(mask_id)
        assert layer is not None and layer.coverage.raster.content_bounds() is not None

        assert viewer.setControlMode(viewer.CONTROL_MODE_MASK_POLYGON)
        _click_polygon(viewer, _polygon_points(viewer))
        QTest.keyClick(viewer, Qt.Key.Key_Enter)
        assert harness.wait_for_mask_undo_depth(mask_id, 2)

        assert layer.coverage.raster.content_bounds() is not None
        assert layer.coverage.has_retained_items
        assert len(layer.coverage.retained.items) == 1
        assert isinstance(layer.coverage.retained.items[0], VectorCoverageItem)
        assert viewer.undoMaskEdit()
        assert layer.coverage.raster.content_bounds() is not None
        assert not layer.coverage.has_retained_items
        assert viewer.redoMaskEdit()
        assert layer.coverage.raster.content_bounds() is not None
        assert layer.coverage.has_retained_items
    finally:
        harness.close()


def _click_polygon(viewer, points: tuple[QPoint, ...]) -> None:
    """Place one open polygon without relying on private tool methods."""
    for point in points:
        QTest.mouseClick(viewer, Qt.MouseButton.LeftButton, pos=point)


def _polygon_points(viewer) -> tuple[QPoint, ...]:
    """Return four panel points defining one non-axis-symmetric polygon."""
    return tuple(
        _panel(viewer, x, y) for x, y in ((140, 80), (270, 105), (245, 230), (125, 200))
    )


def _panel(viewer, x: float, y: float) -> QPoint:
    """Project one scene point into a concrete logical panel point."""
    point = viewer.view().scene_to_panel_point(QPointF(x, y))
    if point is None:
        raise AssertionError("scene point must project into the mounted panel")
    return point.toPoint()
