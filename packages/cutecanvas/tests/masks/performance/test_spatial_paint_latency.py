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
"""Interactive latency proof for the first raster edit of a vector mask."""

from __future__ import annotations

from dataclasses import replace

import pytest
from cutecanvas_test_support.harness.mounted_qpane import MountedQPaneHarness
from cutecanvas_test_support.harness.timing import (
    INTERACTIVE_PERFORMANCE,
    completion_clock,
    interaction_clock,
)
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qpane.sdk.scene import BilinearLayerTransform

pytestmark = INTERACTIVE_PERFORMANCE

_PREPARATION_TIMEOUT_SECONDS = 15.0
_WARMED_PRESS_BUDGET_MS = 35.0


@pytest.mark.parametrize("finite_mapping", [False, True])
def test_prepared_vector_mask_erase_stays_within_interactive_budget(
    qapp: QApplication,
    finite_mapping: bool,
) -> None:
    """Background coverage preparation must keep the first press below 35 ms."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(1600, 1000),
        widget_size=QSize(1082, 639),
        mask_count=1,
        brush_size=64,
    )
    viewer = harness.viewer
    try:
        assert viewer.editor.coverage.rectangle(QRectF(800.0, 0.0, 800.0, 1000.0))
        entry = viewer.listMasksForComposition()[0]
        assert entry.scene_id is not None and entry.layer_id is not None
        if finite_mapping:
            mapping = BilinearLayerTransform(
                (
                    QPointF(800.0, 0.0),
                    QPointF(1600.0, 0.0),
                    QPointF(1600.0, 1000.0),
                    QPointF(800.0, 1000.0),
                ),
                (
                    QPointF(1600.0, 0.0),
                    QPointF(1600.0, 0.0),
                    QPointF(1600.0, 1000.0),
                    QPointF(0.0, 1000.0),
                ),
            )
            assert viewer.setLayerTransform(entry.scene_id, entry.layer_id, mapping)
        assert viewer.setControlMode(viewer.CONTROL_MODE_ERASER)
        scene = viewer.sceneMutationCoordinator().active_scene()
        assert scene is not None
        layer = next(
            candidate
            for candidate in scene.layers
            if candidate.layer_id == entry.layer_id
        )
        deadline = completion_clock() + _PREPARATION_TIMEOUT_SECONDS
        while (
            not viewer.mask_service.stroke_interactions.paint_target_ready(layer)
            and completion_clock() < deadline
        ):
            qapp.processEvents()
            QTest.qWait(1)
        assert viewer.mask_service.stroke_interactions.paint_target_ready(layer)
        if finite_mapping:
            refreshed_layer = replace(
                layer,
                source_revision=layer.source_revision + 1,
            )
            assert viewer.mask_service.stroke_interactions.paint_target_ready(
                refreshed_layer
            )
        panel_point = viewer.view().scene_to_panel_point(QPointF(900.0, 800.0))
        assert panel_point is not None

        started = interaction_clock()
        QTest.mousePress(
            viewer,
            Qt.MouseButton.LeftButton,
            pos=panel_point.toPoint(),
        )
        elapsed_ms = (interaction_clock() - started) * 1000.0
        QTest.mouseRelease(
            viewer,
            Qt.MouseButton.LeftButton,
            pos=panel_point.toPoint(),
        )
        assert harness.wait_for_mask_render_idle()

        assert elapsed_ms < _WARMED_PRESS_BUDGET_MS
    finally:
        harness.close()
