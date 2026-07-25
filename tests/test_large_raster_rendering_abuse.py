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
"""Mounted abuse coverage for large editable-raster presentation."""

from __future__ import annotations

import numpy as np
from cutecanvas import LayerPolicy
from PySide6.QtCore import QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qpane.raster.image_conversion import qimage_to_numpy_argb32

from .harness.mounted_qpane import MountedQPaneHarness
from .harness.timing import (
    INTERACTIVE_PERFORMANCE,
    interaction_clock,
    stable_latency_samples,
)

pytestmark = INTERACTIVE_PERFORMANCE

_POINTER_UPDATE_MEDIAN_BUDGET_MS = 16.0
_POINTER_UPDATE_MAXIMUM_BUDGET_MS = 50.0


def test_large_rgba_half_selection_drag_is_exact_and_frame_responsive(
    qapp: QApplication,
) -> None:
    """Large floating RGBA movement must scale with the visible frame."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(6000, 4000),
        widget_size=QSize(1200, 800),
        mask_count=1,
    )
    viewer = harness.viewer
    try:
        scene = viewer.currentScene()
        assert scene is not None
        source = QImage(1920, 3408, QImage.Format_ARGB32_Premultiplied)
        source.fill(QColor(38, 112, 214, 255))
        layer_id = viewer.addEditableRasterLayer(
            source,
            interaction=LayerPolicy(
                selectable=True,
                movable=True,
                pixel_editable=True,
            ),
        )
        assert layer_id is not None
        assert viewer.setSelectedLayer(scene.scene_id, layer_id)
        viewer.markDirty()
        viewer.update()
        harness.drain_events()

        selection = QImage(1920, 1704, QImage.Format_Grayscale8)
        selection.fill(255)
        assert viewer.setPixelSelection(selection, QRect(0, 0, 1920, 1704))
        resolved_scene_id = viewer._resolve_public_scene_id(scene.scene_id)
        origin = viewer.view().layer_source_to_panel_point(
            resolved_scene_id,
            layer_id,
            QPointF(960.0, 852.0),
        )
        assert origin is not None
        viewer.setControlMode(viewer.CONTROL_MODE_MOVE)
        QTest.mousePress(
            viewer,
            Qt.LeftButton,
            Qt.NoModifier,
            origin.toPoint(),
        )
        harness.drain_events()
        assert viewer._selected_pixel_movement.active

        update_latencies_ms: list[float] = []
        destination = origin
        for displacement in (160, 320, 480, 240, 560, 80, 640, 400) * 2:
            destination = viewer.view().layer_source_to_panel_point(
                resolved_scene_id,
                layer_id,
                QPointF(960.0 + displacement, 852.0),
            )
            assert destination is not None
            started = interaction_clock()
            QTest.mouseMove(viewer, destination.toPoint(), delay=0)
            harness.drain_events()
            update_latencies_ms.append((interaction_clock() - started) * 1000.0)

        renderer = viewer.view().presenter.renderer
        incremental = renderer.get_base_buffer()
        assert incremental is not None
        incremental_pixels = qimage_to_numpy_argb32(incremental.copy())
        viewer.markDirty()
        viewer.update()
        harness.drain_events()
        full_redraw = renderer.get_base_buffer()
        assert full_redraw is not None
        np.testing.assert_array_equal(
            incremental_pixels,
            qimage_to_numpy_argb32(full_redraw.copy()),
        )

        QTest.mouseRelease(
            viewer,
            Qt.LeftButton,
            Qt.NoModifier,
            destination.toPoint(),
        )
        harness.drain_events()
        assert viewer.anchorFloatingPixels()
        harness.drain_events()
        assert viewer.undoSceneEdit()
        harness.drain_events()
        assert viewer.redoSceneEdit()
        harness.drain_events()

        stable_samples = stable_latency_samples(update_latencies_ms)
        assert float(np.median(stable_samples)) < _POINTER_UPDATE_MEDIAN_BUDGET_MS
        assert max(stable_samples) < _POINTER_UPDATE_MAXIMUM_BUDGET_MS
    finally:
        harness.close()
