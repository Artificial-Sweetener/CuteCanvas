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
"""Mounted abuse proof for retained hybrid-mask rendering continuity."""

from __future__ import annotations

import uuid

from cutecanvas.coverage import CoverageGeometryFactory
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize
from PySide6.QtGui import QColor, QTransform
from PySide6.QtWidgets import QApplication
from qpane import (
    HybridDocument,
    HybridPresentationStyle,
    HybridVectorPrimitive,
    RasterBounds,
)
from qpane.hybrid.tile_source import HybridRenderTileSource
from qpane.rendering.render_tile_geometry import visible_tile_requests

from tests.harness.mounted_qpane import MountedQPaneHarness
from tests.harness.timing import (
    average_interaction_latency_ms,
    interaction_clock,
    stable_latency_samples,
)

_INTERACTION_BUDGET_MS = 16.0
_MANY_SHAPE_REFINEMENT_BUDGET_MS = 100.0


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
        deadline = 3000
        while deadline > 0:
            harness.drain_events(wait_ms=2)
            if (
                viewer.view().presenter._render_refinement.pending_count == 0
                and harness.is_mask_tint(harness.color_at(sample))
            ):
                break
            deadline -= 2
        assert deadline > 0

        latencies: list[float] = []
        with harness.observe_presented_frames() as probe:
            for zoom in (0.75, 1.2, 0.55, 1.6, 0.9, 2.0, 0.6, 1.35) * 3:
                started = interaction_clock()
                viewer.applyZoom(zoom, sample)
                latencies.append((interaction_clock() - started) * 1000.0)
                harness.drain_events(wait_ms=1)
            deadline = 5000
            while (
                viewer.view().presenter._render_refinement.pending_count
                and deadline > 0
            ):
                harness.drain_events(wait_ms=2)
                deadline -= 2

        assert deadline > 0
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
            deadline = 3000
            while (
                viewer.view().presenter._render_refinement.pending_count
                and deadline > 0
            ):
                harness.drain_events(wait_ms=2)
                deadline -= 2
        assert deadline > 0
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
        assert harness.wait_for_render_refinement_idle(timeout_ms=5000)
        harness.drain_events(wait_ms=60)
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
        assert len({frame.mask_sample_scales for frame in probe.frames}) == 1
        assert all(
            frame.color_at(point).getRgb() == expected
            for frame in probe.frames
            for point, expected in zip(sample_points, baseline, strict=True)
        )
        cache = viewer.view().presenter._render_tile_cache
        assert 0 < cache.usage_bytes <= cache.budget_bytes
    finally:
        harness.close()
