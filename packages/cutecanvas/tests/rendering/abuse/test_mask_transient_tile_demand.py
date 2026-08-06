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

"""Prove transient mask pixels survive hostile sampled-demand changes."""

from __future__ import annotations

import threading

import cutecanvas.masks.strokes as strokes_module
import pytest
from cutecanvas.masks.stroke_models import MaskStrokeJobResult, MaskStrokeJobSpec
from cutecanvas.painting import BrushCompositor
from cutecanvas_test_support.harness.abuse_model import (
    HarnessPoint,
    PointerKind,
    StrokeAction,
)
from cutecanvas_test_support.harness.input_driver import QtStrokeDriver
from cutecanvas_test_support.harness.mounted_qpane import MountedQPaneHarness
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize
from PySide6.QtWidgets import QApplication
from qpane.sdk.execution import CancellationToken

_CENTER = QPoint(400, 300)
_DISTANT_PAN = QPointF(6000.0, 0.0)


def test_live_erase_preview_recompiles_for_panned_tile_demand(
    qapp: QApplication,
) -> None:
    """Panning during an erase must never present another viewport's tile batch."""
    harness, driver, action = _mounted_eraser(qapp)
    try:
        driver.begin(action)
        for point_index in range(1, len(action.points)):
            driver.move(action, point_index)
        harness.drain_events()
        assert harness.is_background(harness.capture().pixelColor(_CENTER))

        with harness.observe_presented_frames() as presented:
            for pan_x in (6000.0, 5000.0, 5500.0, 4500.0, 6000.0):
                harness.viewer.setPan(QPointF(pan_x, 0.0))
                harness.drain_events()

        assert presented.frames
        assert all(
            harness.is_mask_tint(frame.color_at(_CENTER)) for frame in presented.frames
        )
    finally:
        driver.end(action)
        harness.wait_for_mask_render_idle(timeout_ms=8000)
        harness.wait_for_raster_render_idle(timeout_ms=8000)
        harness.close()


def test_settling_erase_recompiles_when_pan_precedes_durable_commit(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retained erase must follow demand while its durable worker is delayed."""
    worker_started, release_worker = _block_stroke_worker(monkeypatch)
    harness, driver, action = _mounted_eraser(qapp)
    released = False
    try:
        driver.begin(action)
        for point_index in range(1, len(action.points)):
            driver.move(action, point_index)
        harness.drain_events()

        driver.end(action, drain=False)
        released = True
        assert worker_started.wait(timeout=5.0)
        harness.drain_events()

        with harness.observe_presented_frames() as presented:
            harness.viewer.setPan(_DISTANT_PAN)
            harness.drain_events(wait_ms=25)

        assert presented.frames
        assert all(
            harness.is_mask_tint(frame.color_at(_CENTER)) for frame in presented.frames
        )
    finally:
        release_worker.set()
        if not released:
            driver.end(action, drain=False)
        harness.wait_for_mask_render_idle(timeout_ms=8000)
        harness.wait_for_raster_render_idle(timeout_ms=8000)
        harness.close()


def test_committed_erase_discards_retained_tiles_when_view_changes(
    qapp: QApplication,
) -> None:
    """Panning after commit must reveal durable tiles, never the prior view batch."""
    harness, driver, action = _mounted_eraser(qapp)
    released = False
    try:
        driver.begin(action)
        for point_index in range(1, len(action.points)):
            driver.move(action, point_index)
        harness.drain_events()
        driver.end(action, drain=False)
        released = True
        assert harness.wait_for_mask_undo_depth(harness.mask_ids[0], 2)
        assert harness.wait_for_mask_render_idle(timeout_ms=8000)
        assert harness.wait_for_raster_render_idle(timeout_ms=8000)
        assert harness.wait_for_render_refinement_idle(timeout_ms=8000)

        settled_plan = harness.viewer.view().calculateRenderPlan()
        assert settled_plan is not None
        assert settled_plan.transient_raster is None
        with harness.observe_presented_frames() as presented:
            harness.viewer.setPan(_DISTANT_PAN)
            harness.drain_events(wait_ms=25)

        assert presented.frames
        assert all(
            harness.is_mask_tint(frame.color_at(_CENTER)) for frame in presented.frames
        )
    finally:
        if not released:
            driver.end(action, drain=False)
        harness.wait_for_mask_render_idle(timeout_ms=8000)
        harness.wait_for_raster_render_idle(timeout_ms=8000)
        harness.close()


def test_no_op_paint_settlement_clears_after_panned_demand_converges(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A no-op commit must neither flash nor strand a retained contribution."""
    worker_started, release_worker = _block_stroke_worker(monkeypatch)
    harness, driver, action = _mounted_eraser(qapp)
    harness.viewer.setControlMode(harness.viewer.CONTROL_MODE_DRAW_BRUSH)
    released = False
    try:
        driver.begin(action)
        for point_index in range(1, len(action.points)):
            driver.move(action, point_index)
        harness.drain_events()

        driver.end(action, drain=False)
        released = True
        assert worker_started.wait(timeout=5.0)
        harness.drain_events()

        with harness.observe_presented_frames() as presented:
            harness.viewer.setPan(_DISTANT_PAN)
            harness.drain_events(wait_ms=25)
            release_worker.set()
            assert harness.wait_for_mask_render_idle(timeout_ms=8000)
            assert harness.wait_for_raster_render_idle(timeout_ms=8000)
            assert harness.wait_for_render_refinement_idle(timeout_ms=8000)

        assert presented.frames
        assert all(
            harness.is_mask_tint(frame.color_at(_CENTER)) for frame in presented.frames
        )
        plan = harness.viewer.view().calculateRenderPlan()
        assert plan is not None
        assert plan.transient_raster is None
    finally:
        release_worker.set()
        if not released:
            driver.end(action, drain=False)
        harness.wait_for_mask_render_idle(timeout_ms=8000)
        harness.wait_for_raster_render_idle(timeout_ms=8000)
        harness.close()


def _mounted_eraser(
    qapp: QApplication,
) -> tuple[MountedQPaneHarness, QtStrokeDriver, StrokeAction]:
    """Return a zoomed fully covered mask and a genuine erase gesture."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(4096, 4096),
        widget_size=QSize(800, 600),
        brush_size=160,
        cache_budget_mb=96,
    )
    viewer = harness.viewer
    assert viewer.editor.coverage.rectangle(QRectF(0.0, 0.0, 4096.0, 4096.0))
    assert harness.wait_for_mask_render_idle(timeout_ms=8000)
    viewer.applyZoom(4.0, QPointF(_CENTER))
    assert harness.wait_for_render_refinement_idle(timeout_ms=8000)
    viewer.setControlMode(viewer.CONTROL_MODE_ERASER)
    action = StrokeAction(
        device=PointerKind.MOUSE,
        points=(
            HarnessPoint(360, 300),
            HarnessPoint(400, 300),
            HarnessPoint(440, 300),
        ),
        brush_size=160,
    )
    return harness, QtStrokeDriver(harness), action


def _block_stroke_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[threading.Event, threading.Event]:
    """Hold genuine durable stroke work behind a deterministic barrier."""
    worker_started = threading.Event()
    release_worker = threading.Event()
    original_render = strokes_module.render_mask_stroke

    def delayed_render(
        spec: MaskStrokeJobSpec,
        compositor: BrushCompositor,
        cancellation: CancellationToken,
    ) -> MaskStrokeJobResult:
        """Release one production stroke render only when the test permits it."""
        worker_started.set()
        if not release_worker.wait(timeout=5.0):
            raise TimeoutError("mask stroke test worker was not released")
        return original_render(spec, compositor, cancellation)

    monkeypatch.setattr(strokes_module, "render_mask_stroke", delayed_render)
    return worker_started, release_worker
