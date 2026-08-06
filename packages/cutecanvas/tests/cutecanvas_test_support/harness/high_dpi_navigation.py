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
"""Subprocess probe for true-4K high-DPI mask navigation."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QImage, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from qpane.raster.image_conversion import qimage_to_numpy_argb32

from cutecanvas_test_support.harness.mounted_qpane import MountedQPaneHarness
from cutecanvas_test_support.harness.timing import interaction_clock

_RESULT_PREFIX = "HIGH_DPI_NAVIGATION_RESULT="


@dataclass(slots=True)
class _PanMeasurements:
    """Collect real pointer-to-presentation latency across repeated gestures."""

    previous_repairs: int
    latencies_ms: list[float] = field(default_factory=list)
    input_latencies_ms: list[float] = field(default_factory=list)
    presentation_latencies_ms: list[float] = field(default_factory=list)
    renderer_latencies_ms: list[float] = field(default_factory=list)
    repair_frame_indices: list[int] = field(default_factory=list)

    def drive(
        self,
        viewer: QWidget,
        app: QApplication,
        origin: QPoint,
        positions: tuple[QPoint, ...],
    ) -> None:
        """Drive one mounted pan gesture and measure every presented frame."""
        QTest.mousePress(viewer, Qt.LeftButton, Qt.NoModifier, origin)
        try:
            for position in positions:
                frame_index = len(self.latencies_ms)
                started = interaction_clock()
                QTest.mouseMove(viewer, position, delay=0)
                presented = interaction_clock()
                viewer.repaint()
                app.processEvents()
                finished = interaction_clock()
                self.input_latencies_ms.append((presented - started) * 1000.0)
                self.presentation_latencies_ms.append((finished - presented) * 1000.0)
                self.latencies_ms.append((finished - started) * 1000.0)
                renderer = viewer.view().renderer
                frame_metrics = renderer.snapshot_metrics()
                self.renderer_latencies_ms.append(frame_metrics.last_paint_ms)
                if frame_metrics.scroll_repairs > self.previous_repairs:
                    self.repair_frame_indices.append(frame_index)
                    self.previous_repairs = frame_metrics.scroll_repairs
        finally:
            release_position = positions[-1] if positions else origin
            QTest.mouseRelease(
                viewer,
                Qt.LeftButton,
                Qt.NoModifier,
                release_position,
            )


def _wait_for_navigation_settle(
    harness: MountedQPaneHarness,
    operation: str,
) -> None:
    """Wait through exact sampled, raster, and staged navigation publication."""
    if not harness.wait_for_render_refinement_idle(timeout_ms=8000):
        raise RuntimeError(f"{operation} sampled refinement did not settle")
    if not harness.wait_for_raster_render_idle(timeout_ms=8000):
        raise RuntimeError(f"{operation} raster refinement did not settle")
    harness.drain_events(wait_ms=30)


def main() -> None:
    """Measure the reported 5x navigation flow at a 4K physical viewport."""
    app = QApplication.instance() or QApplication([])
    harness = MountedQPaneHarness(
        app,
        image_size=QSize(3440, 1440),
        widget_size=QSize(2194, 1234),
        mask_count=1,
        cache_budget_mb=384,
    )
    viewer = harness.viewer
    center = viewer.rect().center()
    try:
        document_path_text = os.environ.get("CUTECANVAS_ABUSE_DOCUMENT")
        document_path = None if document_path_text is None else Path(document_path_text)
        if document_path is not None:
            viewer.editor.persistence.load(document_path)
        else:
            layer = viewer.mask_service.assets.get_layer(harness.mask_ids[0])
            if layer is None:
                raise RuntimeError("high-DPI probe mask is unavailable")

            def paint_mask(pixels: np.ndarray, _image: QImage) -> None:
                """Paint sparse broad coverage matching the reported document shape."""
                pixels.fill(0)
                pixels[0:512, 1024:2560] = 255
                pixels[512:1024, 512:2560] = 255

            layer.coverage.raster.mutate(paint_mask)
            viewer.mask_service.invalidateMaskCache(harness.mask_ids[0])
            viewer.mask_service.controller.mask_updated.emit(None, QRect())
        viewer.setControlMode(viewer.CONTROL_MODE_PANZOOM)
        viewer.applyZoom(5.0, center)
        if not harness.wait_for_mask_render_idle(timeout_ms=8000):
            raise RuntimeError("mask rendering did not settle")
        if not harness.wait_for_render_refinement_idle(
            timeout_ms=8000,
            include_prefetch=True,
        ):
            raise RuntimeError("sampled rendering did not settle")
        if not harness.wait_for_raster_render_idle(timeout_ms=8000):
            raise RuntimeError("raster rendering did not settle")
        harness.drain_events(wait_ms=60)

        physical = viewer.physicalViewportRect().size()
        metrics_before = viewer.view().renderer.snapshot_metrics()
        pan_positions = tuple(
            center
            + QPoint(
                round(math.cos(index * math.tau / 120.0) * 850.0),
                round(math.sin(index * math.tau / 120.0) * 450.0),
            )
            for index in range(240)
        ) + (center,)
        measurements = _PanMeasurements(metrics_before.scroll_repairs)
        with harness.observe_renderer_paint_durations() as paint_probe:
            measurements.drive(viewer, app, center, pan_positions)
            _wait_for_navigation_settle(harness, "circular pan")
            for direction in (*((-1,) * 8), *((1,) * 8)):
                sweep = tuple(
                    center
                    + QPoint(
                        round(direction * 850.0 * step / 24.0),
                        round(math.sin(step * math.pi / 12.0) * 45.0),
                    )
                    for step in range(1, 25)
                )
                measurements.drive(viewer, app, center, sweep)
                _wait_for_navigation_settle(harness, "long pan sweep")
            metrics_after_pan = viewer.view().renderer.snapshot_metrics()
            pan_paint_count = len(paint_probe.durations_ms)

            zoom_latencies: list[float] = []
            for delta in (120, 120, -120, -120, 120, -120):
                wheel = QWheelEvent(
                    QPointF(center),
                    QPointF(viewer.mapToGlobal(center)),
                    QPoint(),
                    QPoint(0, delta),
                    Qt.NoButton,
                    Qt.NoModifier,
                    Qt.ScrollPhase.ScrollUpdate,
                    False,
                )
                started = interaction_clock()
                QApplication.sendEvent(viewer, wheel)
                viewer.repaint()
                app.processEvents()
                zoom_latencies.append((interaction_clock() - started) * 1000.0)
                QTest.qWait(35)
            _wait_for_navigation_settle(harness, "wheel zoom")
        metrics_after = viewer.view().renderer.snapshot_metrics()
        staged_metrics = viewer.view().renderer.navigation_refinement_metrics()
        settled = viewer.view().renderer.get_base_buffer().copy()
        viewer.view().renderer.markDirty()
        viewer.update()
        harness.drain_events()
        clean = viewer.view().renderer.get_base_buffer().copy()
        settled_pixels = qimage_to_numpy_argb32(settled).astype(np.int16)
        clean_pixels = qimage_to_numpy_argb32(clean).astype(np.int16)
        settled_difference = np.max(
            np.abs(settled_pixels - clean_pixels),
            axis=2,
        )
        mismatched_y, mismatched_x = np.nonzero(settled_difference)
        current = viewer.editor.compositions.current
        result = {
            "physical_width": physical.width(),
            "physical_height": physical.height(),
            "device_pixel_ratio": viewer.devicePixelRatioF(),
            "loaded_document": (
                None if document_path is None else str(document_path.resolve())
            ),
            "mask_count": len(viewer.listMasksForComposition()),
            "active_composition_id": (None if current is None else str(current.id)),
            "active_composition_title": (
                None if current is None else current.state.title
            ),
            "active_layer_count": (0 if current is None else len(current.layers)),
            "pan_latencies_ms": measurements.latencies_ms,
            "pan_input_latencies_ms": measurements.input_latencies_ms,
            "pan_presentation_latencies_ms": measurements.presentation_latencies_ms,
            "pan_renderer_latencies_ms": measurements.renderer_latencies_ms,
            "repair_frame_indices": measurements.repair_frame_indices,
            "zoom_latencies_ms": zoom_latencies,
            "renderer_paint_latencies_ms": paint_probe.durations_ms,
            "pan_renderer_paint_latencies_ms": (
                paint_probe.durations_ms[:pan_paint_count]
            ),
            "scroll_attempts": (
                metrics_after.scroll_attempts - metrics_before.scroll_attempts
            ),
            "scroll_hits": metrics_after.scroll_hits - metrics_before.scroll_hits,
            "scroll_misses": metrics_after.scroll_misses - metrics_before.scroll_misses,
            "scroll_repairs": (
                metrics_after.scroll_repairs - metrics_before.scroll_repairs
            ),
            "full_redraws": metrics_after.full_redraws - metrics_before.full_redraws,
            "pan_full_redraws": (
                metrics_after_pan.full_redraws - metrics_before.full_redraws
            ),
            "zoom_full_redraws": (
                metrics_after.full_redraws - metrics_after_pan.full_redraws
            ),
            "settled_matches_clean": settled == clean,
            "settled_mismatch_pixels": int(mismatched_x.size),
            "settled_maximum_channel_delta": int(settled_difference.max(initial=0)),
            "settled_mismatch_bounds": (
                None
                if not mismatched_x.size
                else [
                    int(mismatched_x.min()),
                    int(mismatched_y.min()),
                    int(mismatched_x.max()),
                    int(mismatched_y.max()),
                ]
            ),
            "staged_completed_frames": staged_metrics.completed_frames,
            "staged_cancelled_frames": staged_metrics.cancelled_frames,
            "staged_maximum_step_ms": staged_metrics.maximum_step_ms,
            "staged_maximum_publish_ms": staged_metrics.maximum_publish_ms,
            "staged_maximum_worker_ms": staged_metrics.maximum_worker_ms,
        }
        print(f"{_RESULT_PREFIX}{json.dumps(result, sort_keys=True)}")
    finally:
        harness.close()


if __name__ == "__main__":
    main()
