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
"""Mounted abuse proof for retained hybrid-mask rendering continuity."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid

import numpy as np
import pytest
from cutecanvas.coverage import CoverageGeometryFactory
from cutecanvas_test_support.harness.mounted_qpane import MountedQPaneHarness
from cutecanvas_test_support.harness.timing import (
    INTERACTIVE_PERFORMANCE,
    absolute_latency_assertions_are_isolated,
    average_interaction_latency_ms,
    interaction_clock,
    stable_latency_samples,
    tail_interaction_latency_ms,
)
from cutecanvas_test_support.repository import repository_root
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QTransform, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qpane import (
    HybridDocument,
    HybridPresentationStyle,
    HybridVectorPrimitive,
    RasterBounds,
)
from qpane.hybrid.tile_source import HybridRenderTileSource
from qpane.raster.image_conversion import qimage_to_numpy_argb32
from qpane.rendering.render_tile_geometry import visible_tile_requests

pytestmark = INTERACTIVE_PERFORMANCE

_INTERACTION_BUDGET_MS = 16.0
_SIXTY_HZ_FRAME_BUDGET_MS = 1000.0 / 60.0
_LARGE_VIEWPORT_AVERAGE_BUDGET_MS = 35.0
_LARGE_VIEWPORT_TAIL_BUDGET_MS = 60.0
_FOUR_K_VIEWPORT_AVERAGE_BUDGET_MS = 50.0
_FOUR_K_VIEWPORT_TAIL_BUDGET_MS = 75.0
_NAVIGATION_STALL_BUDGET_MS = 150.0
_MANY_SHAPE_REFINEMENT_BUDGET_MS = 100.0
_HIGH_DPI_RESULT_PREFIX = "HIGH_DPI_NAVIGATION_RESULT="


def _settle_sampled_render_for_latency(harness: MountedQPaneHarness) -> None:
    """Remove renderer contention only when wall latency is authoritative."""
    if absolute_latency_assertions_are_isolated():
        assert harness.wait_for_sampled_render_idle(timeout_ms=8000)


def _capture_authoritative_settled_frame(harness: MountedQPaneHarness) -> QImage:
    """Capture exact pixels after hosted runs discard provisional navigation."""
    if not absolute_latency_assertions_are_isolated():
        harness.viewer.view().renderer.markDirty()
        harness.viewer.repaint()
        harness.drain_events(wait_ms=30)
    return harness.capture()


def _wait_for_presented_mask_layers(
    harness: MountedQPaneHarness,
    *,
    expected_layers: int,
    timeout_ms: int = 20_000,
) -> bool:
    """Wait for one exact displayed frame containing every expected mask."""
    deadline = time.perf_counter() + timeout_ms / 1000.0
    harness.viewer.view().renderer.markDirty()
    with harness.observe_presented_frames() as probe:
        while time.perf_counter() < deadline:
            harness.viewer.repaint()
            if probe.frames and probe.frames[-1].mask_layer_count == expected_layers:
                return True
            QTest.qWait(1)
    return False


def test_retained_vector_mask_zoom_storm_never_presents_blank_or_partial_frames(
    qapp: QApplication,
) -> None:
    """Every intermediate zoom frame must retain one complete mask revision."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(1600, 900),
        widget_size=QSize(960, 540),
        cache_budget_mb=96,
    )
    viewer = harness.viewer
    sample = QPoint(480, 270)
    interior_points = tuple(
        QPoint(x, y)
        for y in (90, 180, 270, 360, 450)
        for x in (160, 320, 480, 640, 800)
    )
    try:
        assert viewer.editor.coverage.rectangle(QRectF(0.0, 0.0, 1600.0, 900.0))
        assert (
            harness.wait_for_mask_tint(sample, timeout_ms=8000).latency_ms is not None
        )

        latencies: list[float] = []
        with harness.observe_presented_frames() as probe:
            for zoom in (0.75, 1.2, 0.55, 1.6, 0.9, 2.0, 0.6, 1.35) * 3:
                started = interaction_clock()
                viewer.applyZoom(zoom, sample)
                latencies.append((interaction_clock() - started) * 1000.0)
                harness.drain_events(wait_ms=1)

        assert probe.frames
        assert all(frame.mask_layer_count == 1 for frame in probe.frames)
        assert all(
            harness.is_mask_tint(frame.color_at(point))
            for frame in probe.frames
            for point in interior_points
        )
        assert max(stable_latency_samples(latencies, parallel_batch_size=8)) < (
            _INTERACTION_BUDGET_MS
        )
        cache = viewer.view().presenter._render_tile_cache
        assert 0 < cache.usage_bytes <= cache.budget_bytes

        presentation_latencies: list[float] = []
        with harness.observe_presented_frames() as color_probe:
            for color in (
                QColor(230, 70, 90),
                QColor(45, 195, 120),
                QColor(70, 110, 235),
                QColor(210, 150, 35),
            ):
                started = interaction_clock()
                assert viewer.setMaskProperties(harness.mask_ids[0], color=color)
                presentation_latencies.append((interaction_clock() - started) * 1000.0)
                harness.drain_events(wait_ms=1)
        assert color_probe.frames
        assert all(frame.mask_layer_count == 1 for frame in color_probe.frames)
        assert all(
            harness.is_mask_tint(frame.color_at(point))
            for frame in color_probe.frames
            for point in interior_points
        )
        assert (
            max(stable_latency_samples(presentation_latencies, parallel_batch_size=4))
            < _INTERACTION_BUDGET_MS
        )
    finally:
        harness.close()


@pytest.mark.parametrize("raster_backed", (False, True), ids=("vector", "raster"))
@pytest.mark.parametrize("pan_axis", ("horizontal", "vertical"))
def test_zoomed_mask_pan_crosses_cold_tile_boundary_without_pop_in(
    qapp: QApplication,
    raster_backed: bool,
    pan_axis: str,
) -> None:
    """A direct pan must retain complete mask coverage across cold tile boundaries."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(4096, 4096),
        widget_size=QSize(800, 600),
        cache_budget_mb=8,
    )
    viewer = harness.viewer
    center = QPoint(400, 300)
    horizontal = pan_axis == "horizontal"
    probe_points = tuple(
        QPoint(position, center.y()) if horizontal else QPoint(center.x(), position)
        for position in (20, 80, 200, center.x() if horizontal else center.y())
    )
    try:
        if raster_backed:
            layer = viewer.mask_service.assets.get_layer(harness.mask_ids[0])
            assert layer is not None

            def paint_mask(pixels: np.ndarray, _image: QImage) -> None:
                """Paint complete raster coverage across every sampled tile."""
                pixels.fill(255)

            layer.coverage.raster.mutate(paint_mask)
            viewer.mask_service.invalidateMaskCache(harness.mask_ids[0])
            viewer.mask_service.controller.mask_updated.emit(None, QRect())
        else:
            assert viewer.editor.coverage.rectangle(QRectF(0.0, 0.0, 4096.0, 4096.0))
        viewer.setControlMode(viewer.CONTROL_MODE_PANZOOM)
        viewer.applyZoom(5.0, center)
        assert harness.wait_for_mask_render_idle(timeout_ms=8000)
        _settle_sampled_render_for_latency(harness)
        viewer.view().renderer.markDirty()
        viewer.repaint()
        harness.drain_events(wait_ms=30)
        for point in probe_points:
            assert (
                harness.wait_for_mask_tint(
                    point,
                    timeout_ms=8000,
                ).latency_ms
                is not None
            )

        frames: list[tuple[int, tuple[bool, ...]]] = []
        pan_latencies: list[float] = []
        active_worker_counts: list[int] = []
        metrics_before = viewer.view().renderer.snapshot_metrics()
        QTest.mousePress(viewer, Qt.LeftButton, Qt.NoModifier, center)
        try:
            for delta in range(300, 3300, 300):
                started = interaction_clock()
                pan_delta = QPoint(delta, 0) if horizontal else QPoint(0, delta)
                QTest.mouseMove(viewer, center + pan_delta, delay=0)
                harness.drain_events()
                pan_latencies.append((interaction_clock() - started) * 1000.0)
                active_worker_counts.append(
                    len(viewer.view().presenter._render_refinement._pending)
                )
                frames.append(
                    (
                        delta,
                        tuple(
                            harness.is_mask_tint(harness.color_at(point))
                            for point in probe_points
                        ),
                    )
                )
        finally:
            QTest.mouseRelease(
                viewer,
                Qt.LeftButton,
                Qt.NoModifier,
                center + (QPoint(3000, 0) if horizontal else QPoint(0, 3000)),
            )

        release_tint = tuple(
            harness.is_mask_tint(harness.color_at(point)) for point in probe_points
        )
        metrics_after = viewer.view().renderer.snapshot_metrics()
        stable_pan = stable_latency_samples(pan_latencies, parallel_batch_size=4)
        assert all(all(tinted) for _delta, tinted in frames), frames
        assert all(release_tint), release_tint
        assert not any(active_worker_counts), active_worker_counts
        assert metrics_after.scroll_attempts - metrics_before.scroll_attempts == len(
            frames
        )
        assert metrics_after.scroll_hits - metrics_before.scroll_hits >= len(frames) - 1
        assert sum(stable_pan) / len(stable_pan) < _SIXTY_HZ_FRAME_BUDGET_MS
        assert (
            tail_interaction_latency_ms(
                pan_latencies,
                parallel_batch_size=4,
            )
            < 30.0
        )
    finally:
        harness.close()


def test_many_retained_shapes_refine_one_large_viewport_with_bounded_cpu() -> None:
    """A dense authored document must not repeat viewport work per tile."""
    geometry = CoverageGeometryFactory()
    primitives = tuple(
        HybridVectorPrimitive(
            uuid.uuid5(uuid.NAMESPACE_OID, f"hybrid-abuse-{index}"),
            geometry.rectangle(
                QRectF(
                    float((index * 193) % 4000),
                    float((index * 131) % 4000),
                    96.0,
                    72.0,
                )
            ),
            RasterBounds(
                (index * 193) % 4000,
                (index * 131) % 4000,
                96,
                72,
            ),
        )
        for index in range(400)
    )
    source = HybridRenderTileSource(
        HybridDocument(
            uuid.uuid4(),
            RasterBounds(0, 0, 4096, 4096),
            primitives,
            revision=1,
        ),
        HybridPresentationStyle(QColor(40, 190, 180)),
    )
    requests = visible_tile_requests(
        source_kind=source.source_kind,
        source_id=source.source_id,
        revision_key=source.revision_key,
        fallback_key=source.fallback_key,
        bounds=source.bounds,
        source_to_panel=QTransform.fromScale(0.25, 0.25),
        panel_rect=QRectF(0.0, 0.0, 1024.0, 1024.0),
        device_pixel_ratio=1.0,
        budget_bytes=64 * 1024 * 1024,
    )
    assert requests is not None and len(requests) > 1

    products = ()

    def render_once() -> None:
        """Render one complete batch and retain it for correctness assertions."""
        nonlocal products
        products = source.render_tiles(requests, lambda: False)

    elapsed_ms = average_interaction_latency_ms(
        render_once,
        repetitions=3,
    )

    assert len(products) == len(requests)
    assert elapsed_ms < _MANY_SHAPE_REFINEMENT_BUDGET_MS


def test_rapid_mask_pan_keeps_pixels_and_sampling_density_stable(
    qapp: QApplication,
) -> None:
    """A real-worker pan storm must never flash or alternate mask density."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(4096, 4096),
        widget_size=QSize(800, 600),
        cache_budget_mb=96,
    )
    viewer = harness.viewer
    sample_points = tuple(
        QPoint(x, y) for y in (60, 180, 300, 420, 540) for x in (50, 200, 400, 600, 750)
    )
    try:
        assert viewer.editor.coverage.rectangle(QRectF(0.0, 0.0, 4096.0, 4096.0))
        viewer.applyZoom(4.0, QPointF(400.0, 300.0))
        _settle_sampled_render_for_latency(harness)
        viewer.view().renderer.markDirty()
        viewer.repaint()
        harness.drain_events(wait_ms=60)
        for point in sample_points:
            assert (
                harness.wait_for_mask_tint(point, timeout_ms=8000).latency_ms
                is not None
            )
        baseline = tuple(harness.color_at(point).getRgb() for point in sample_points)
        assert all(harness.is_mask_tint(QColor(*color)) for color in baseline)

        viewer.setPan(QPointF(6000.0, 0.0))
        harness.drain_events(wait_ms=1)
        latencies: list[float] = []
        for pan_x in (0.0, 6000.0) * 24:
            started = interaction_clock()
            viewer.setPan(QPointF(pan_x, 0.0))
            latencies.append((interaction_clock() - started) * 1000.0)
            harness.drain_events()
        assert max(stable_latency_samples(latencies, parallel_batch_size=8)) < (
            _INTERACTION_BUDGET_MS
        )

        with harness.observe_presented_frames() as probe:
            for pan_x in (0.0, 6000.0) * 24:
                viewer.setPan(QPointF(pan_x, 0.0))
                harness.drain_events()

        assert probe.frames
        assert all(frame.mask_layer_count == 1 for frame in probe.frames)
        assert all(frame.mask_sample_scales for frame in probe.frames)
        assert all(set(frame.mask_sample_scales) == {1.0} for frame in probe.frames)
        assert all(
            frame.color_at(point).getRgb() == expected
            for frame in probe.frames
            for point, expected in zip(sample_points, baseline, strict=True)
        )
        cache = viewer.view().presenter._render_tile_cache
        assert 0 < cache.usage_bytes <= cache.budget_bytes
    finally:
        harness.close()


@pytest.mark.parametrize(
    (
        "widget_size",
        "cache_budget_mb",
        "center",
        "initial_zoom",
        "probe_zooms",
        "measured_zooms",
        "average_budget_ms",
        "tail_budget_ms",
    ),
    (
        (
            QSize(1920, 1080),
            192,
            QPoint(960, 540),
            0.75,
            (0.8, 0.7, 0.85, 0.75),
            (0.78, 0.81, 0.78, 0.75),
            _LARGE_VIEWPORT_AVERAGE_BUDGET_MS,
            _LARGE_VIEWPORT_TAIL_BUDGET_MS,
        ),
        (
            QSize(3840, 2160),
            384,
            QPoint(1920, 1080),
            1.25,
            (1.2, 1.1, 1.3, 1.25),
            (1.28, 1.31, 1.28, 1.25),
            _FOUR_K_VIEWPORT_AVERAGE_BUDGET_MS,
            _FOUR_K_VIEWPORT_TAIL_BUDGET_MS,
        ),
    ),
    ids=("1080p-viewport", "4k-viewport"),
)
def test_four_overlapping_4k_masks_navigate_fluidly_without_dropped_layers(
    qapp: QApplication,
    widget_size: QSize,
    cache_budget_mb: int,
    center: QPoint,
    initial_zoom: float,
    probe_zooms: tuple[float, ...],
    measured_zooms: tuple[float, ...],
    average_budget_ms: float,
    tail_budget_ms: float,
) -> None:
    """Large presented frames must keep every mask while pan and zoom stay fluid."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(3840, 2160),
        widget_size=widget_size,
        mask_count=4,
        cache_budget_mb=cache_budget_mb,
    )
    viewer = harness.viewer
    initial_cache_preferences = {
        consumer_id: consumer["preferred_bytes"]
        for consumer_id, consumer in viewer.cacheCoordinator.snapshot()[
            "consumers"
        ].items()
    }
    try:
        colors = (
            QColor(230, 65, 90),
            QColor(45, 195, 120),
            QColor(65, 105, 235),
            QColor(220, 155, 35),
        )
        for index, (mask_id, color) in enumerate(
            zip(harness.mask_ids, colors, strict=True)
        ):
            harness.activate_mask(index)
            assert viewer.setMaskProperties(mask_id, color=color, opacity=0.3)
            assert viewer.editor.coverage.rectangle(QRectF(0.0, 0.0, 3840.0, 2160.0))
        harness.activate_mask(0)
        viewer.applyZoom(initial_zoom, center)
        assert harness.wait_for_mask_render_idle(timeout_ms=8000)
        _settle_sampled_render_for_latency(harness)
        assert harness.wait_for_raster_render_idle(timeout_ms=8000)
        harness.drain_events(wait_ms=30)
        assert _wait_for_presented_mask_layers(harness, expected_layers=4)

        with harness.observe_presented_frames() as probe:
            for pan in (
                QPointF(-360.0, -180.0),
                QPointF(360.0, -180.0),
                QPointF(360.0, 180.0),
                QPointF(-360.0, 180.0),
                QPointF(0.0, 0.0),
            ):
                viewer.setPan(pan)
                harness.drain_events()
            for zoom in probe_zooms:
                viewer.applyZoom(zoom, center)
                harness.drain_events()
        assert probe.frames
        assert all(frame.mask_layer_count == 4 for frame in probe.frames)
        center_colors = tuple(frame.color_at(center).getRgb() for frame in probe.frames)
        assert all(
            not harness.is_background(frame.color_at(center)) for frame in probe.frames
        ), center_colors
        _settle_sampled_render_for_latency(harness)
        harness.drain_events(wait_ms=30)

        pan_latencies: list[float] = []
        zoom_latencies: list[float] = []
        viewer.setPan(QPointF())
        harness.drain_events()
        metrics_before = viewer.view().renderer.snapshot_metrics()
        for _ in range(3):
            for pan in (
                QPointF(48.0, 0.0),
                QPointF(96.0, 0.0),
                QPointF(144.0, 0.0),
                QPointF(192.0, 0.0),
                QPointF(192.0, 48.0),
                QPointF(192.0, 96.0),
                QPointF(144.0, 96.0),
                QPointF(96.0, 96.0),
                QPointF(48.0, 96.0),
                QPointF(0.0, 96.0),
                QPointF(0.0, 48.0),
                QPointF(0.0, 0.0),
            ):
                started = interaction_clock()
                viewer.setPan(pan)
                harness.drain_events()
                pan_latencies.append((interaction_clock() - started) * 1000.0)
        _settle_sampled_render_for_latency(harness)
        harness.drain_events(wait_ms=30)
        for _ in range(3):
            for zoom in measured_zooms:
                started = interaction_clock()
                viewer.applyZoom(zoom, center)
                harness.drain_events()
                zoom_latencies.append((interaction_clock() - started) * 1000.0)
        metrics_after = viewer.view().renderer.snapshot_metrics()

        stable_pan = stable_latency_samples(pan_latencies, parallel_batch_size=4)
        stable_zoom = stable_latency_samples(zoom_latencies, parallel_batch_size=4)
        assert sum(stable_pan) / len(stable_pan) < average_budget_ms, (
            stable_pan,
            metrics_before,
            metrics_after,
        )
        assert sum(stable_zoom) / len(stable_zoom) < average_budget_ms, (
            stable_zoom,
            metrics_before,
            metrics_after,
        )
        assert (
            tail_interaction_latency_ms(
                pan_latencies,
                parallel_batch_size=4,
            )
            < tail_budget_ms
        ), (
            stable_pan,
            metrics_before,
            metrics_after,
        )
        assert (
            tail_interaction_latency_ms(
                zoom_latencies,
                parallel_batch_size=4,
            )
            < tail_budget_ms
        ), (
            stable_zoom,
            metrics_before,
            metrics_after,
        )
        assert max(stable_pan) < _NAVIGATION_STALL_BUDGET_MS
        assert max(stable_zoom) < _NAVIGATION_STALL_BUDGET_MS
        assert harness.wait_for_mask_render_idle(timeout_ms=8000)
        _settle_sampled_render_for_latency(harness)
        assert harness.wait_for_raster_render_idle(timeout_ms=8000)
        harness.drain_events(wait_ms=60)
        settled = _capture_authoritative_settled_frame(harness)
        viewer.view().renderer.markDirty()
        viewer.update()
        clean = harness.capture()
        assert settled == clean, _image_difference_summary(settled, clean)
        cache = viewer.view().presenter._render_tile_cache
        assert 0 < cache.usage_bytes <= cache.budget_bytes
        final_cache_preferences = {
            consumer_id: consumer["preferred_bytes"]
            for consumer_id, consumer in viewer.cacheCoordinator.snapshot()[
                "consumers"
            ].items()
        }
        assert final_cache_preferences == initial_cache_preferences
    finally:
        harness.close()


@pytest.mark.parametrize("mask_count", (1, 2))
def test_painted_1440p_masks_navigate_fluidly_in_a_four_k_viewport(
    qapp: QApplication,
    mask_count: int,
) -> None:
    """Warm raster masks must pan and zoom fluidly at a true 4K viewport."""
    viewport_size = QSize(3840, 2160)
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(2560, 1440),
        widget_size=viewport_size,
        mask_count=mask_count,
        cache_budget_mb=384,
    )
    viewer = harness.viewer
    center = QPoint(viewport_size.width() // 2, viewport_size.height() // 2)
    try:
        for index, mask_id in enumerate(harness.mask_ids):
            layer = viewer.mask_service.assets.get_layer(mask_id)
            assert layer is not None

            def paint_mask(
                pixels: np.ndarray,
                _image: QImage,
                *,
                layer_index: int = index,
            ) -> None:
                """Paint broad intersecting raster coverage like a real brush session."""
                pixels.fill(0)
                pixels[
                    120 + layer_index * 140 : 1260,
                    180 : 2380 - layer_index * 120,
                ] = 255
                pixels[
                    360:1080,
                    640 + layer_index * 220 : 1920 + layer_index * 180,
                ] = 0

            layer.coverage.raster.mutate(paint_mask)
            viewer.mask_service.invalidateMaskCache(mask_id)
        viewer.mask_service.controller.mask_updated.emit(None, QRect())
        viewer.setControlMode(viewer.CONTROL_MODE_PANZOOM)
        viewer.applyZoom(2.0, center)
        _settle_sampled_render_for_latency(harness)
        assert harness.wait_for_raster_render_idle(timeout_ms=8000)
        harness.drain_events(wait_ms=60)
        assert _wait_for_presented_mask_layers(
            harness,
            expected_layers=mask_count,
        )

        positions = tuple(
            center + QPoint(step * 8, ((step % 5) - 2) * 5) for step in range(1, 31)
        )
        metrics_before = viewer.view().renderer.snapshot_metrics()
        pan_latencies = _drive_pointer_pan(harness, center, positions)
        metrics_after = viewer.view().renderer.snapshot_metrics()

        zoom_latencies: list[float] = []
        with harness.observe_navigation_transform_durations() as zoom_probe:
            zoom_steps = (120, 120, -120, -120, 120, -120)
            for index, delta in enumerate(zoom_steps):
                wheel = QWheelEvent(
                    QPointF(center),
                    QPointF(viewer.mapToGlobal(center)),
                    QPoint(),
                    QPoint(0, delta),
                    Qt.NoButton,
                    Qt.NoModifier,
                    (
                        Qt.ScrollPhase.ScrollBegin
                        if index == 0
                        else Qt.ScrollPhase.ScrollUpdate
                    ),
                    False,
                )
                started = interaction_clock()
                QApplication.sendEvent(viewer, wheel)
                harness.drain_events()
                zoom_latencies.append((interaction_clock() - started) * 1000.0)
                harness.drain_events(wait_ms=35)
            wheel_end = QWheelEvent(
                QPointF(center),
                QPointF(viewer.mapToGlobal(center)),
                QPoint(),
                QPoint(),
                Qt.NoButton,
                Qt.NoModifier,
                Qt.ScrollPhase.ScrollEnd,
                False,
            )
            QApplication.sendEvent(viewer, wheel_end)
            harness.drain_events()
        assert zoom_probe.durations_ms

        if absolute_latency_assertions_are_isolated():
            stable_pan = stable_latency_samples(
                pan_latencies,
                parallel_batch_size=4,
            )
            stable_zoom = stable_latency_samples(
                zoom_latencies,
                parallel_batch_size=4,
            )
            assert sum(stable_pan) / len(stable_pan) < _SIXTY_HZ_FRAME_BUDGET_MS, (
                stable_pan,
                metrics_before,
                metrics_after,
            )
            assert (
                tail_interaction_latency_ms(
                    pan_latencies,
                    parallel_batch_size=4,
                )
                < 30.0
            ), (
                stable_pan,
                metrics_before,
                metrics_after,
            )
            assert sum(stable_zoom) / len(stable_zoom) < _SIXTY_HZ_FRAME_BUDGET_MS, (
                stable_zoom,
                viewer.view().renderer.snapshot_metrics(),
            )
            assert (
                tail_interaction_latency_ms(
                    zoom_latencies,
                    parallel_batch_size=4,
                )
                < 30.0
            ), stable_zoom
            assert max(zoom_probe.durations_ms) < 2.0
        assert metrics_after.scroll_hits - metrics_before.scroll_hits >= 28
        _settle_sampled_render_for_latency(harness)
        assert harness.wait_for_raster_render_idle(timeout_ms=8000)
        harness.drain_events(wait_ms=60)
        settled = _capture_authoritative_settled_frame(harness)
        viewer.view().renderer.markDirty()
        viewer.update()
        clean = harness.capture()
        assert settled == clean, _image_difference_summary(settled, clean)
    finally:
        harness.close()


@pytest.mark.interactive_performance
def test_reported_high_dpi_five_x_mask_navigation_is_fluid() -> None:
    """The 4K physical, 175%-DPR, 5x workflow must reuse every warm frame."""
    root = repository_root()
    environment = os.environ.copy()
    # The subprocess owns Qt independently while retaining the hosted CPU-clock
    # policy when CI executes other jobs on the same runner.
    environment.pop("PYTEST_XDIST_WORKER", None)
    environment.update(
        {
            "QT_QPA_PLATFORM": "offscreen",
            "QT_SCALE_FACTOR": "1.75",
            "PYTHONPATH": os.pathsep.join(
                (
                    str(root / "packages" / "cutecanvas" / "src"),
                    str(root / "packages" / "qpane" / "src"),
                    str(root / "packages" / "cutecanvas" / "tests"),
                    str(root),
                )
            ),
        }
    )
    completed = subprocess.run(
        (
            sys.executable,
            "-m",
            "cutecanvas_test_support.harness.high_dpi_navigation",
        ),
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, (completed.stdout, completed.stderr)
    result_line = next(
        (
            line
            for line in completed.stdout.splitlines()
            if line.startswith(_HIGH_DPI_RESULT_PREFIX)
        ),
        None,
    )
    assert result_line is not None, completed.stdout
    result = json.loads(result_line.removeprefix(_HIGH_DPI_RESULT_PREFIX))
    pan_latencies = result["pan_latencies_ms"]
    zoom_latencies = result["zoom_latencies_ms"]
    assert result["physical_width"] >= 3839.0
    assert result["physical_height"] >= 2159.0
    assert result["device_pixel_ratio"] == pytest.approx(1.75)
    assert sum(pan_latencies) / len(pan_latencies) < _SIXTY_HZ_FRAME_BUDGET_MS
    assert sum(zoom_latencies) / len(zoom_latencies) < _SIXTY_HZ_FRAME_BUDGET_MS
    assert tail_interaction_latency_ms(pan_latencies) < 25.0
    assert tail_interaction_latency_ms(zoom_latencies) < 25.0
    assert result["scroll_attempts"] >= 29
    assert result["scroll_hits"] >= result["scroll_attempts"]
    assert result["scroll_misses"] == 0, result["miss_frame_indices"]
    assert result["scroll_repairs"] >= 8
    redraws = {
        "pan": result["pan_full_redraws"],
        "zoom": result["zoom_full_redraws"],
        "total": result["full_redraws"],
        "zoom_trace": result["zoom_redraw_trace"],
        "zoom_end": result["zoom_end_full_redraws"],
        "zoom_settle": result["zoom_settle_full_redraws"],
    }
    assert redraws["pan"] == 0, redraws
    assert redraws["zoom"] == 0, redraws
    assert result["staged_maximum_step_ms"] < 16.0
    assert result["staged_maximum_publish_ms"] < 16.0
    if result["absolute_latency_isolated"]:
        assert result["staged_completed_frames"] > 0
        assert result["staged_maximum_worker_ms"] > 0.0
    else:
        assert result["staged_pending_observed"]
    assert result["settled_matches_clean"]


def _image_difference_summary(actual: QImage, expected: QImage) -> dict[str, object]:
    """Return compact geometry and channel magnitude for unequal render buffers."""
    actual_pixels = qimage_to_numpy_argb32(actual.copy())
    expected_pixels = qimage_to_numpy_argb32(expected.copy())
    changed = np.any(actual_pixels != expected_pixels, axis=2)
    rows, columns = np.nonzero(changed)
    if not rows.size:
        return {"changed_pixels": 0}
    delta = np.abs(actual_pixels.astype(np.int16) - expected_pixels.astype(np.int16))
    return {
        "changed_pixels": int(rows.size),
        "bounds": (
            int(columns.min()),
            int(rows.min()),
            int(columns.max()),
            int(rows.max()),
        ),
        "maximum_channel_delta": int(delta.max()),
    }


def _drive_pointer_pan(
    harness: MountedQPaneHarness,
    origin: QPoint,
    positions: tuple[QPoint, ...],
) -> list[float]:
    """Return per-frame latency for one real navigation-tool drag."""
    latencies: list[float] = []
    QTest.mousePress(harness.viewer, Qt.LeftButton, Qt.NoModifier, origin)
    try:
        for position in positions:
            started = interaction_clock()
            QTest.mouseMove(harness.viewer, position, delay=0)
            harness.drain_events()
            latencies.append((interaction_clock() - started) * 1000.0)
    finally:
        QTest.mouseRelease(
            harness.viewer,
            Qt.LeftButton,
            Qt.NoModifier,
            positions[-1],
        )
    return latencies
