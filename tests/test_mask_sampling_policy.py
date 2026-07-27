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

"""Mounted regression proof for sharp high-zoom mask presentation."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication
from qpane.scene.model import LayerKind

from tests.harness.mounted_qpane import MountedQPaneHarness


def test_high_zoom_mask_uses_native_samples_and_sharp_pixel_edges(
    qapp: QApplication,
) -> None:
    """A settled mask should expose the same solid pixel grid as raster layers."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(16, 16),
        widget_size=QSize(64, 64),
        cache_budget_mb=32,
    )
    viewer = harness.viewer
    coverage = QImage(2, 1, QImage.Format.Format_Grayscale8)
    coverage.setPixelColor(0, 0, QColor(255, 255, 255))
    coverage.setPixelColor(1, 0, QColor(0, 0, 0))
    try:
        assert viewer.addCoverageImage(coverage, QRect(7, 8, 2, 1)) is not None
        viewer.applyZoom(4.0, QPoint(32, 32))
        assert harness.wait_for_render_refinement_idle(timeout_ms=3000)

        plan = viewer.view().calculateRenderPlan()
        assert plan is not None
        mask_items = tuple(
            item for item in plan.render_items if item.descriptor.kind is LayerKind.MASK
        )
        assert mask_items
        assert all(not item.render_hint_enabled for item in mask_items)
        assert {
            round(
                tile.image_source_rect.width() / tile.source_rect.width(),
                6,
            )
            for item in mask_items
            for tile in item.tiles
        } == {1.0}

        coordinates = viewer.activeMaskLayerCoordinates()
        covered_center = coordinates.source_to_panel(QPointF(7.5, 8.5))
        clear_center = coordinates.source_to_panel(QPointF(8.5, 8.5))
        assert covered_center is not None
        assert clear_center is not None
        frame = harness.capture()
        covered_point = covered_center.toPoint()
        clear_point = clear_center.toPoint()
        tinted = frame.pixelColor(covered_point)
        assert harness.is_mask_tint(tinted)
        assert all(
            frame.pixelColor(covered_point + QPoint(offset, 0)) == tinted
            for offset in (-1, 0, 1)
        )
        assert all(
            frame.pixelColor(clear_point + QPoint(offset, 0)) == QColor("white")
            for offset in (-1, 0, 1)
        )
    finally:
        harness.close()
