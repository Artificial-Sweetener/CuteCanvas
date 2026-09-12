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

"""Prove mask presentation remains correct without cache capacity."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QSize
from PySide6.QtWidgets import QApplication

from cutecanvas_test_support.harness.abuse_model import (
    HarnessPoint,
    PointerKind,
    StrokeAction,
)
from cutecanvas_test_support.harness.input_driver import QtStrokeDriver
from cutecanvas_test_support.harness.mounted_qpane import MountedQPaneHarness


def test_mask_paints_when_memory_pressure_disables_all_cache_retention(
    qapp: QApplication,
) -> None:
    """Present canonical mask pixels while every coordinated cache budget is zero."""

    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(640, 480),
        widget_size=QSize(420, 320),
        mask_count=1,
        brush_size=40,
        cache_budget_mb=1,
    )
    driver = QtStrokeDriver(harness)
    painted_point = QPoint(210, 160)
    stroke = StrokeAction(
        PointerKind.MOUSE,
        points=(HarnessPoint(180, 160), HarnessPoint(240, 160)),
        brush_size=40,
    )
    try:
        harness.viewer.applySettings(cache={"mode": "hard", "budget_mb": 0})
        driver.begin(stroke)
        driver.move(stroke, 1)
        driver.end(stroke)

        assert harness.wait_for_mask_undo_depth(harness.mask_ids[0], 1)
        assert harness.wait_for_mask_tint(painted_point).latency_ms is not None
        assert harness.viewer.mask_service.controller.renders.cache_usage_bytes == 0
    finally:
        harness.close()
