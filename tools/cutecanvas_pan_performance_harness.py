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

"""Profile the exact high-resolution CuteCanvas pan regression headlessly."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import statistics
import sys
import time
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any, Self

if __name__ == "__main__":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_SCALE_FACTOR", "1.75")

import cutecanvas
import numpy as np
from cutecanvas import CuteCanvas
from PySide6.QtCore import QEvent, QPoint, QPointF, QSize, Qt
from PySide6.QtGui import (
    QBackingStore,
    QImage,
    QPaintEngine,
    QPainter,
    QPaintEvent,
    QRegion,
)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import qpane

_RESULT_VERSION = 1
_DEFAULT_DOCUMENT = Path(r"C:\Users\imkno\test.cutecanvas")
_DEFAULT_LOGICAL_VIEWPORT = QSize(3840, 2160)
_DEFAULT_ZOOM = 5.0
_DEFAULT_STEPS = 96
_DEFAULT_RADIUS_X = 1500
_DEFAULT_RADIUS_Y = 800
_TARGET_P95_MS = 30.0
_SIXTY_HZ_FRAME_MS = 1000.0 / 60.0
_LARGE_SPIKE_MS = 100.0
_FILTER_ROUNDING_TOLERANCE = 1


@dataclass(frozen=True, slots=True)
class FrameTiming:
    """Record the immutable whole-cycle metric and nested diagnostic phases."""

    step_index: int
    pointer_x: int
    pointer_y: int
    pan_x: float
    pan_y: float
    pointer_to_present_ms: float
    input_dispatch_ms: float
    event_drain_ms: float
    paint_event_ms: float
    paint_region_logical_pixels: float
    planning_ms: float
    scroll_attempt_ms: float
    surface_scroll_ms: float
    repair_ms: float
    backing_paint_ms: float
    presentation_ms: float
    paint_event_count: int
    widget_update_count: int
    widget_scroll_count: int
    cursor_set_count: int
    scroll_attempted: bool
    scroll_repaired: bool
    full_redraw: bool


@dataclass(frozen=True, slots=True)
class LatencySummary:
    """Summarize one non-empty latency population in milliseconds."""

    count: int
    mean_ms: float
    median_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float


@dataclass(slots=True)
class PhaseRecorder:
    """Attribute nested synchronous phase durations to one active pan update."""

    active_step: int | None = None
    _durations: dict[int, dict[str, list[float]]] = field(default_factory=dict)

    def record(self, phase: str, elapsed_ms: float) -> None:
        """Retain one duration while a measured pointer update is active."""
        if self.active_step is None:
            return
        phases = self._durations.setdefault(self.active_step, {})
        phases.setdefault(phase, []).append(float(elapsed_ms))

    def total(self, step_index: int, phase: str) -> float:
        """Return the summed duration for one phase in one pointer update."""
        return float(sum(self._durations.get(step_index, {}).get(phase, ())))

    def count(self, step_index: int, phase: str) -> int:
        """Return the number of phase invocations in one pointer update."""
        return len(self._durations.get(step_index, {}).get(phase, ()))


class TimedCuteCanvas(CuteCanvas):
    """Expose complete CuteCanvas paint-event timing to the local harness."""

    def __init__(self, recorder: PhaseRecorder) -> None:
        """Create a production canvas with a timing-only observer."""
        self._pan_performance_recorder = recorder
        super().__init__(features=("mask",))
        self._native_backing_probe = False

    def paintEvent(self, event: QPaintEvent) -> None:
        """Time the complete production widget paint event."""
        logical_pixels = sum(rect.width() * rect.height() for rect in event.region())
        self._pan_performance_recorder.record(
            "paint_region_logical_pixels",
            float(logical_pixels),
        )
        started = time.perf_counter()
        try:
            super().paintEvent(event)
        finally:
            self._pan_performance_recorder.record(
                "paint_event",
                (time.perf_counter() - started) * 1000.0,
            )


class NativeBackingTimedCuteCanvas(TimedCuteCanvas):
    """Exercise a direct native software backing store for limit analysis."""

    def __init__(self, recorder: PhaseRecorder) -> None:
        """Create a native child window whose backing store is owned explicitly."""
        super().__init__(recorder)
        self._native_backing_probe = True
        self._probe_backing_store: QBackingStore | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_PaintOnScreen, True)

    def paintEngine(self) -> QPaintEngine | None:
        """Disable QWidget's paint engine for explicit backing-store ownership."""
        return None

    def paintEvent(self, event: QPaintEvent) -> None:
        """Time one direct native-backing presentation."""
        logical_pixels = sum(rect.width() * rect.height() for rect in event.region())
        self._pan_performance_recorder.record(
            "paint_region_logical_pixels",
            float(logical_pixels),
        )
        started = time.perf_counter()
        try:
            self._paint_native_backing(event)
        finally:
            self._pan_performance_recorder.record(
                "paint_event",
                (time.perf_counter() - started) * 1000.0,
            )

    def _paint_native_backing(self, event: QPaintEvent) -> None:
        """Present the production retained frame through one explicit backing store."""
        self.view().ensure_view_alignment()
        presenter = self.view().presenter
        render_plan = presenter._take_pending_navigation_plan()
        if render_plan is None:
            render_plan = presenter.calculateRenderPlan(is_blank=self._is_blank)
        if render_plan is not None:
            presenter._ensure_buffer_matches_widget()
            presenter.renderer.paint(render_plan)
            presenter._last_scroll_reuse_signature = (
                presenter._scroll_reuse_signature_for_plan(render_plan)
            )
        window = self.windowHandle()
        if window is None:
            raise RuntimeError("native backing probe requires a native QWindow")
        if self._probe_backing_store is None:
            self._probe_backing_store = QBackingStore(window)
        if self._probe_backing_store.size() != self.size():
            self._probe_backing_store.resize(self.size())
        region = QRegion(event.region())
        self._probe_backing_store.beginPaint(QRegion())
        painter = QPainter(self._probe_backing_store.paintDevice())
        try:
            presenter.renderer.draw_base_buffer(painter)
        finally:
            painter.end()
            self._probe_backing_store.endPaint()
        self._probe_backing_store.flush(region, window)


class MethodPhaseProbe:
    """Time one optional Python method without changing its behavior."""

    def __init__(
        self,
        owner: object,
        method_name: str,
        phase: str,
        recorder: PhaseRecorder,
    ) -> None:
        """Bind an optional method to one diagnostic phase."""
        self._owner = owner
        self._method_name = method_name
        self._phase = phase
        self._recorder = recorder
        self._original: Callable[..., Any] | None = None

    @property
    def available(self) -> bool:
        """Return whether the target exposes a replaceable callable method."""
        return callable(getattr(self._owner, self._method_name, None))

    def __enter__(self) -> Self:
        """Install the transparent timing wrapper when the method exists."""
        original = getattr(self._owner, self._method_name)
        if not callable(original):
            raise TypeError(f"{self._method_name} must be callable")
        self._original = original

        def measured(*args: object, **kwargs: object) -> Any:
            """Delegate one method invocation and retain its wall duration."""
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                self._recorder.record(
                    self._phase,
                    (time.perf_counter() - started) * 1000.0,
                )

        setattr(self._owner, self._method_name, measured)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Restore the original bound method."""
        del exc_type, exc_value, traceback
        if self._original is not None:
            setattr(self._owner, self._method_name, self._original)
            self._original = None


class DocumentPanHarness:
    """Mount the supplied document and drive the exact headless pan workload."""

    def __init__(
        self,
        application: QApplication,
        document_path: Path,
        *,
        logical_viewport: QSize,
        zoom: float,
        steps: int,
        radius_x: int,
        radius_y: int,
        tile_size: int | None = None,
        native_backing_probe: bool = False,
    ) -> None:
        """Load and settle one production CuteCanvas document."""
        self._application = application
        self._document_path = document_path.resolve()
        self._logical_viewport = QSize(logical_viewport)
        self._zoom = float(zoom)
        self._steps = int(steps)
        self._radius_x = int(radius_x)
        self._radius_y = int(radius_y)
        self._tile_size = None if tile_size is None else int(tile_size)
        self._recorder = PhaseRecorder()
        canvas_type = (
            NativeBackingTimedCuteCanvas if native_backing_probe else TimedCuteCanvas
        )
        self.canvas = canvas_type(self._recorder)
        self._mount()

    @property
    def pointer_positions(self) -> tuple[QPoint, ...]:
        """Return the immutable measured pointer sequence."""
        return elliptical_pointer_path(
            self.canvas.size(),
            steps=self._steps,
            radius_x=self._radius_x,
            radius_y=self._radius_y,
        )

    def run_timing(self) -> list[FrameTiming]:
        """Measure every pointer update from dispatch through presentation."""
        renderer = self.canvas.view().presenter.renderer
        probes = self.phase_probes()
        timings: list[FrameTiming] = []
        center = self.canvas.rect().center()
        with ExitStack() as stack:
            for probe in probes:
                if probe.available:
                    stack.enter_context(probe)
            QTest.mousePress(
                self.canvas,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                center,
            )
            try:
                for step_index, position in enumerate(self.pointer_positions):
                    before = renderer.snapshot_metrics()
                    self._recorder.active_step = step_index
                    started = time.perf_counter()
                    QTest.mouseMove(self.canvas, position, delay=0)
                    dispatched = time.perf_counter()
                    self._application.processEvents()
                    presented = time.perf_counter()
                    if self._recorder.count(step_index, "paint_event") < 1:
                        raise RuntimeError(
                            "pan update completed without a presented paint event"
                        )
                    after = renderer.snapshot_metrics()
                    timings.append(
                        self._frame_timing(
                            step_index,
                            position,
                            before,
                            after,
                            started=started,
                            dispatched=dispatched,
                            presented=presented,
                        )
                    )
            finally:
                self._recorder.active_step = None
                QTest.mouseRelease(
                    self.canvas,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                    self.pointer_positions[-1],
                )
        self._wait_for_render_idle()
        return timings

    def phase_probes(self) -> list[MethodPhaseProbe]:
        """Return the production phase probes shared by synthetic and trace replay."""
        renderer = self.canvas.view().presenter.renderer
        presenter = self.canvas.view().presenter
        surface = getattr(renderer, "_surface", None)
        probes = [
            MethodPhaseProbe(
                self.canvas,
                "update",
                "widget_update",
                self._recorder,
            ),
            MethodPhaseProbe(
                self.canvas,
                "scroll",
                "widget_scroll",
                self._recorder,
            ),
            MethodPhaseProbe(
                self.canvas,
                "setCursor",
                "cursor_set",
                self._recorder,
            ),
            MethodPhaseProbe(
                presenter,
                "calculateRenderPlan",
                "planning",
                self._recorder,
            ),
            MethodPhaseProbe(
                renderer,
                "tryScrollBuffers",
                "scroll_attempt",
                self._recorder,
            ),
            MethodPhaseProbe(
                renderer,
                "_repair_base_buffer_strips",
                "repair",
                self._recorder,
            ),
            MethodPhaseProbe(
                renderer,
                "paint",
                "backing_paint",
                self._recorder,
            ),
            MethodPhaseProbe(
                renderer,
                "draw_base_buffer",
                "presentation",
                self._recorder,
            ),
        ]
        if surface is not None:
            probes.append(
                MethodPhaseProbe(
                    surface,
                    "scroll",
                    "surface_scroll",
                    self._recorder,
                )
            )
        return probes

    def run_correctness_replay(
        self,
        frames: Sequence[FrameTiming],
        *,
        checkpoint_limit: int,
        artifact_root: Path,
    ) -> dict[str, object]:
        """Compare risky incrementally presented frames with forced clean redraws."""
        checkpoints = select_correctness_steps(frames, limit=checkpoint_limit)
        if not checkpoints:
            return {
                "passed": True,
                "checked_steps": [],
                "failure_count": 0,
                "first_failure": None,
                "channel_tolerance": _FILTER_ROUNDING_TOLERANCE,
                "exact_mismatch_checkpoints": 0,
                "max_observed_channel_delta": 0,
            }
        self.canvas.setPan(QPointF())
        self._force_clean_redraw()
        center = self.canvas.rect().center()
        failures: list[dict[str, object]] = []
        exact_mismatch_checkpoints = 0
        maximum_channel_delta = 0
        QTest.mousePress(
            self.canvas,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            center,
        )
        try:
            for step_index, position in enumerate(self.pointer_positions):
                QTest.mouseMove(self.canvas, position, delay=0)
                self.canvas.repaint()
                self._application.processEvents()
                if step_index not in checkpoints:
                    continue
                renderer = self.canvas.view().presenter.renderer
                incremental_base = renderer.get_base_buffer()
                if incremental_base is None:
                    raise RuntimeError("renderer lost its backing surface")
                incremental_plan = renderer.get_current_render_plan()
                incremental = self.canvas.grab().toImage()
                self._force_clean_redraw()
                clean_base = renderer.get_base_buffer()
                if clean_base is None:
                    raise RuntimeError("renderer lost its clean backing surface")
                clean_plan = renderer.get_current_render_plan()
                clean = self.canvas.grab().toImage()
                difference = compare_images(
                    incremental,
                    clean,
                    channel_tolerance=_FILTER_ROUNDING_TOLERANCE,
                )
                base_difference = compare_images(
                    incremental_base,
                    clean_base,
                    channel_tolerance=_FILTER_ROUNDING_TOLERANCE,
                )
                maximum_channel_delta = max(
                    maximum_channel_delta,
                    int(difference["max_channel_delta"]),
                )
                if difference["exact_mismatch_pixels"]:
                    exact_mismatch_checkpoints += 1
                if difference["mismatch_pixels"]:
                    directory = artifact_root / f"step-{step_index:03d}"
                    save_difference_artifacts(directory, incremental, clean)
                    save_difference_artifacts(
                        directory / "base",
                        incremental_base,
                        clean_base,
                    )
                    failures.append(
                        {
                            "step_index": step_index,
                            "artifact_directory": str(directory.resolve()),
                            "base_difference": base_difference,
                            "plan_transforms_match": _plan_transforms(incremental_plan)
                            == _plan_transforms(clean_plan),
                            "incremental_plan_transforms": _plan_transforms(
                                incremental_plan
                            ),
                            "clean_plan_transforms": _plan_transforms(clean_plan),
                            **difference,
                        }
                    )
        finally:
            QTest.mouseRelease(
                self.canvas,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                self.pointer_positions[-1],
            )
        return {
            "passed": not failures,
            "checked_steps": list(checkpoints),
            "failure_count": len(failures),
            "first_failure": None if not failures else failures[0],
            "channel_tolerance": _FILTER_ROUNDING_TOLERANCE,
            "exact_mismatch_checkpoints": exact_mismatch_checkpoints,
            "max_observed_channel_delta": maximum_channel_delta,
        }

    def close(self) -> None:
        """Release the offscreen canvas and drain deferred deletion."""
        self.canvas.close()
        self.canvas.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self._application.processEvents()

    def _mount(self) -> None:
        """Configure, load, zoom, and settle the exact document workload."""
        self.canvas.resize(self._logical_viewport)
        overrides: dict[str, object] = {
            "drag_out_enabled": False,
            "smooth_zoom_enabled": False,
            "touch_inertia_enabled": False,
        }
        if self._tile_size is not None:
            overrides["tile_size"] = self._tile_size
        self.canvas.applySettings(
            **overrides,
        )
        self.canvas.setControlMode(self.canvas.CONTROL_MODE_PANZOOM)
        self.canvas.show()
        self._application.processEvents()
        self.canvas.editor.persistence.load(self._document_path)
        self._application.processEvents()
        self.canvas.view().ensure_view_alignment(force=True)
        self.canvas.applyZoom(self._zoom, self.canvas.rect().center())
        self.canvas.setPan(QPointF())
        self._force_clean_redraw()
        self._wait_for_render_idle(timeout_seconds=30.0)
        if self.canvas.size() != self._logical_viewport:
            raise RuntimeError(
                "mounted logical viewport changed: "
                f"requested={self._logical_viewport.width()}x"
                f"{self._logical_viewport.height()} actual={self.canvas.width()}x"
                f"{self.canvas.height()}"
            )
        if not math.isclose(
            self.canvas.currentZoom(),
            self._zoom,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            raise RuntimeError(
                "mounted canvas did not retain requested zoom: "
                f"requested={self._zoom:g} actual={self.canvas.currentZoom():g}"
            )

    def _force_clean_redraw(self) -> None:
        """Invalidate the whole renderer buffer and synchronously present it."""
        renderer = self.canvas.view().presenter.renderer
        renderer.markDirty()
        self.canvas.repaint()
        self._application.processEvents()

    def _wait_for_render_idle(self, *, timeout_seconds: float = 15.0) -> None:
        """Wait until document, tile, and refinement work stays quiescent."""
        deadline = time.perf_counter() + timeout_seconds
        idle_since: float | None = None
        while time.perf_counter() < deadline:
            self._application.processEvents()
            view = self.canvas.view()
            presenter = view.presenter
            pyramid_manager = getattr(view, "pyramid_manager", None)
            if pyramid_manager is None:
                pyramid_manager = view._pyramid_manager
            tile_metrics = presenter.tile_manager.snapshot_metrics()
            mask_service = getattr(self.canvas, "mask_service", None)
            mask_idle = mask_service is None or not bool(
                mask_service.hasPendingRenderWork()
            )
            refinement = getattr(presenter, "_render_refinement", None)
            refinement_idle = refinement is None or (
                int(getattr(refinement, "pending_count", 0)) == 0
                and not bool(getattr(refinement, "prefetch_pending", False))
            )
            tile_grid_runtime = getattr(presenter, "_tile_grid_runtime", None)
            tile_grid_idle = tile_grid_runtime is None or not bool(
                getattr(tile_grid_runtime, "pending", False)
            )
            idle = (
                mask_idle
                and not pyramid_manager.pending_asset_keys()
                and not pyramid_manager.pending_retry_asset_keys()
                and int(tile_metrics.active_jobs) == 0
                and int(tile_metrics.pending_retries) == 0
                and refinement_idle
                and tile_grid_idle
                and not bool(getattr(presenter, "navigation_refinement_pending", False))
            )
            now = time.perf_counter()
            idle_since = now if idle and idle_since is None else idle_since
            if not idle:
                idle_since = None
            if idle_since is not None and now - idle_since >= 0.025:
                self._application.processEvents()
                return
            QTest.qWait(1)
        raise TimeoutError("CuteCanvas pan harness did not reach render idle")

    def _frame_timing(
        self,
        step_index: int,
        position: QPoint,
        before: object,
        after: object,
        *,
        started: float,
        dispatched: float,
        presented: float,
    ) -> FrameTiming:
        """Build one timing record from immutable and diagnostic observations."""
        current_pan = QPointF(self.canvas.view().viewport.pan)
        return FrameTiming(
            step_index=step_index,
            pointer_x=position.x(),
            pointer_y=position.y(),
            pan_x=current_pan.x(),
            pan_y=current_pan.y(),
            pointer_to_present_ms=(presented - started) * 1000.0,
            input_dispatch_ms=(dispatched - started) * 1000.0,
            event_drain_ms=(presented - dispatched) * 1000.0,
            paint_event_ms=self._recorder.total(step_index, "paint_event"),
            paint_region_logical_pixels=self._recorder.total(
                step_index,
                "paint_region_logical_pixels",
            ),
            planning_ms=self._recorder.total(step_index, "planning"),
            scroll_attempt_ms=self._recorder.total(step_index, "scroll_attempt"),
            surface_scroll_ms=self._recorder.total(step_index, "surface_scroll"),
            repair_ms=self._recorder.total(step_index, "repair"),
            backing_paint_ms=self._recorder.total(step_index, "backing_paint"),
            presentation_ms=self._recorder.total(step_index, "presentation"),
            paint_event_count=self._recorder.count(step_index, "paint_event"),
            widget_update_count=self._recorder.count(step_index, "widget_update"),
            widget_scroll_count=self._recorder.count(step_index, "widget_scroll"),
            cursor_set_count=self._recorder.count(step_index, "cursor_set"),
            scroll_attempted=_counter_increased(before, after, "scroll_attempts"),
            scroll_repaired=_counter_increased(before, after, "scroll_repairs"),
            full_redraw=_counter_increased(before, after, "full_redraws"),
        )


def elliptical_pointer_path(
    viewport_size: QSize,
    *,
    steps: int,
    radius_x: int,
    radius_y: int,
) -> tuple[QPoint, ...]:
    """Return the exact rapid ellipse plus center-return reproducer path."""
    if viewport_size.isEmpty():
        raise ValueError("viewport size must be non-empty")
    if steps < 4:
        raise ValueError("steps must be at least four")
    if radius_x < 1 or radius_y < 1:
        raise ValueError("pointer radii must be positive")
    center = QPoint(viewport_size.width() // 2, viewport_size.height() // 2)
    ellipse = tuple(
        center
        + QPoint(
            round(radius_x * math.cos(index * math.tau / steps)),
            round(radius_y * math.sin(index * math.tau / steps)),
        )
        for index in range(steps)
    )
    positions = ellipse + (center,)
    if not all(
        0 <= point.x() < viewport_size.width()
        and 0 <= point.y() < viewport_size.height()
        for point in positions
    ):
        raise ValueError("pointer path must remain inside the viewport")
    return positions


def summarize_latencies(values: Sequence[float]) -> LatencySummary | None:
    """Return nearest-rank latency statistics for one metric."""
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    return LatencySummary(
        count=len(ordered),
        mean_ms=statistics.fmean(ordered),
        median_ms=statistics.median(ordered),
        p90_ms=_nearest_rank(ordered, 0.90),
        p95_ms=_nearest_rank(ordered, 0.95),
        p99_ms=_nearest_rank(ordered, 0.99),
        max_ms=ordered[-1],
    )


def build_summaries(
    frames: Sequence[FrameTiming],
) -> dict[str, LatencySummary | None]:
    """Summarize the primary whole-cycle metric and diagnostic phases."""
    names = (
        "pointer_to_present",
        "input_dispatch",
        "event_drain",
        "paint_event",
        "planning",
        "scroll_attempt",
        "surface_scroll",
        "repair",
        "backing_paint",
        "presentation",
    )
    summaries = {
        name: summarize_latencies(
            [float(getattr(frame, f"{name}_ms")) for frame in frames]
        )
        for name in names
    }
    summaries["repair_pointer_to_present"] = summarize_latencies(
        [frame.pointer_to_present_ms for frame in frames if frame.scroll_repaired]
    )
    return summaries


def select_correctness_steps(
    frames: Sequence[FrameTiming],
    *,
    limit: int,
) -> tuple[int, ...]:
    """Select slow, repaired, and path-distributed clean-redraw checkpoints."""
    if limit <= 0 or not frames:
        return ()
    count = min(limit, len(frames))
    slowest = sorted(
        range(len(frames)),
        key=lambda index: frames[index].pointer_to_present_ms,
        reverse=True,
    )
    repairs = [index for index, frame in enumerate(frames) if frame.scroll_repaired]
    selected: list[int] = []
    candidates = (
        slowest[: max(1, count // 3)]
        + _evenly_spaced_indices(repairs, max(1, count // 3))
        + _evenly_spaced_indices(list(range(len(frames))), count)
        + [0, len(frames) - 1]
    )
    for index in candidates:
        if index not in selected:
            selected.append(index)
        if len(selected) >= count:
            break
    return tuple(sorted(selected))


def _plan_transforms(plan: object) -> list[list[float]]:
    """Return render-item matrices for differential diagnostics."""
    render_items = getattr(plan, "render_items", ())
    return [
        [
            transform.m11(),
            transform.m12(),
            transform.m13(),
            transform.m21(),
            transform.m22(),
            transform.m23(),
            transform.m31(),
            transform.m32(),
            transform.m33(),
        ]
        for item in render_items
        if (transform := getattr(item, "transform", None)) is not None
    ]


def compare_images(
    actual: QImage,
    expected: QImage,
    *,
    channel_tolerance: int = 0,
) -> dict[str, object]:
    """Return RGBA mismatch statistics above one explicit channel tolerance."""
    if not 0 <= channel_tolerance <= 255:
        raise ValueError("channel_tolerance must be between zero and 255")
    if actual.size() != expected.size():
        mismatch_pixels = max(
            actual.width() * actual.height(),
            expected.width() * expected.height(),
        )
        return {
            "mismatch_pixels": mismatch_pixels,
            "exact_mismatch_pixels": mismatch_pixels,
            "max_channel_delta": 255,
            "size_mismatch": True,
        }
    actual_rgba = actual.convertToFormat(QImage.Format.Format_RGBA8888)
    expected_rgba = expected.convertToFormat(QImage.Format.Format_RGBA8888)
    actual_pixels = (
        np.frombuffer(
            actual_rgba.constBits(),
            dtype=np.uint8,
            count=actual_rgba.sizeInBytes(),
        )
        .reshape(actual_rgba.height(), actual_rgba.bytesPerLine())[
            :, : actual_rgba.width() * 4
        ]
        .reshape(actual_rgba.height(), actual_rgba.width(), 4)
    )
    expected_pixels = (
        np.frombuffer(
            expected_rgba.constBits(),
            dtype=np.uint8,
            count=expected_rgba.sizeInBytes(),
        )
        .reshape(expected_rgba.height(), expected_rgba.bytesPerLine())[
            :, : expected_rgba.width() * 4
        ]
        .reshape(expected_rgba.height(), expected_rgba.width(), 4)
    )
    delta = np.abs(actual_pixels.astype(np.int16) - expected_pixels.astype(np.int16))
    pixel_delta = delta.max(axis=2)
    return {
        "mismatch_pixels": int((pixel_delta > channel_tolerance).sum()),
        "exact_mismatch_pixels": int((pixel_delta > 0).sum()),
        "max_channel_delta": int(delta.max(initial=0)),
        "size_mismatch": False,
    }


def _evenly_spaced_indices(indices: Sequence[int], count: int) -> list[int]:
    """Return up to ``count`` values distributed across ordered indices."""
    if count <= 0 or not indices:
        return []
    if count >= len(indices):
        return list(indices)
    if count == 1:
        return [indices[len(indices) // 2]]
    return [
        indices[round(position * (len(indices) - 1) / (count - 1))]
        for position in range(count)
    ]


def save_difference_artifacts(
    directory: Path,
    actual: QImage,
    expected: QImage,
) -> None:
    """Save the incremental and clean widget captures for one failure."""
    directory.mkdir(parents=True, exist_ok=True)
    if not actual.save(str(directory / "incremental.png")):
        raise RuntimeError("failed to save incremental correctness artifact")
    if not expected.save(str(directory / "clean.png")):
        raise RuntimeError("failed to save clean correctness artifact")


def _parse_args(arguments: Sequence[str]) -> argparse.Namespace:
    """Parse the immutable reproducer and local artifact options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document", type=Path, default=_DEFAULT_DOCUMENT)
    parser.add_argument("--logical-width", type=int, default=3840)
    parser.add_argument("--logical-height", type=int, default=2160)
    parser.add_argument("--zoom", type=float, default=_DEFAULT_ZOOM)
    parser.add_argument("--steps", type=int, default=_DEFAULT_STEPS)
    parser.add_argument("--radius-x", type=int, default=_DEFAULT_RADIUS_X)
    parser.add_argument("--radius-y", type=int, default=_DEFAULT_RADIUS_Y)
    parser.add_argument("--correctness-steps", type=int, default=4)
    parser.add_argument("--no-correctness", action="store_true")
    parser.add_argument("--native-backing-probe", action="store_true")
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("pan-performance-artifacts") / "cutecanvas-4k-5x",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the exact document timing pass and differential correctness replay."""
    options = _parse_args(arguments if arguments is not None else sys.argv[1:])
    if not options.document.is_file():
        raise FileNotFoundError(options.document)
    application = QApplication.instance() or QApplication(sys.argv)
    if application.platformName().lower() != "offscreen":
        raise RuntimeError("the CuteCanvas pan harness requires offscreen Qt")
    logical_viewport = QSize(options.logical_width, options.logical_height)
    harness = DocumentPanHarness(
        application,
        options.document,
        logical_viewport=logical_viewport,
        zoom=options.zoom,
        steps=options.steps,
        radius_x=options.radius_x,
        radius_y=options.radius_y,
        native_backing_probe=options.native_backing_probe,
    )
    try:
        frames = harness.run_timing()
        summaries = build_summaries(frames)
        result = _build_result(
            harness,
            options.document,
            frames=frames,
            summaries=summaries,
        )
        if not options.no_correctness:
            result["correctness"] = harness.run_correctness_replay(
                frames,
                checkpoint_limit=options.correctness_steps,
                artifact_root=options.artifact_root,
            )
    finally:
        harness.close()
    _print_result(result)
    if options.output is not None:
        options.output.parent.mkdir(parents=True, exist_ok=True)
        options.output.write_text(
            json.dumps(result, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(f"JSON: {options.output.resolve()}")
    correctness = result.get("correctness")
    return int(isinstance(correctness, dict) and correctness.get("passed") is False)


def _build_result(
    harness: DocumentPanHarness,
    document_path: Path,
    *,
    frames: Sequence[FrameTiming],
    summaries: dict[str, LatencySummary | None],
) -> dict[str, object]:
    """Build the complete workload-identified benchmark result."""
    physical = harness.canvas.physicalViewportRect().size()
    dpr = float(harness.canvas.devicePixelRatioF())
    primary = summaries["pointer_to_present"]
    if primary is None:
        raise RuntimeError("timing run produced no frames")
    stat = document_path.stat()
    return {
        "version": _RESULT_VERSION,
        "primary_metric": "pointer_to_present_ms",
        "platform": {
            "qt": harness._application.platformName().lower(),
            "python": platform.python_version(),
            "system": platform.platform(),
            "qt_scale_factor": os.environ.get("QT_SCALE_FACTOR"),
        },
        "sources": {
            "cutecanvas": str(Path(cutecanvas.__file__).resolve()),
            "qpane": str(Path(qpane.__file__).resolve()),
        },
        "document": {
            "path": str(document_path.resolve()),
            "size": stat.st_size,
            "sha256": _sha256(document_path),
        },
        "workload": {
            "logical_width": harness.canvas.width(),
            "logical_height": harness.canvas.height(),
            "physical_width": round(physical.width()),
            "physical_height": round(physical.height()),
            "device_pixel_ratio": dpr,
            "zoom": harness._zoom,
            "ellipse_steps": harness._steps,
            "native_backing_probe": harness.canvas._native_backing_probe,
            "measured_frames": len(frames),
            "radius_x": harness._radius_x,
            "radius_y": harness._radius_y,
        },
        "summaries": {
            name: None if summary is None else asdict(summary)
            for name, summary in summaries.items()
        },
        "counts": {
            "frames": len(frames),
            "paint_events": sum(frame.paint_event_count for frame in frames),
            "scroll_attempts": sum(frame.scroll_attempted for frame in frames),
            "scroll_repairs": sum(frame.scroll_repaired for frame in frames),
            "full_redraws": sum(frame.full_redraw for frame in frames),
            "frames_over_target_ms": sum(
                frame.pointer_to_present_ms >= _TARGET_P95_MS for frame in frames
            ),
            "frames_over_16_67_ms": sum(
                frame.pointer_to_present_ms >= _SIXTY_HZ_FRAME_MS for frame in frames
            ),
            "frames_over_100_ms": sum(
                frame.pointer_to_present_ms >= _LARGE_SPIKE_MS for frame in frames
            ),
        },
        "target": {
            "p95_below_30_ms": primary.p95_ms < _TARGET_P95_MS,
            "no_frames_over_100_ms": primary.max_ms < _LARGE_SPIKE_MS,
            "passed": (
                primary.p95_ms < _TARGET_P95_MS and primary.max_ms < _LARGE_SPIKE_MS
            ),
        },
        "frames": [asdict(frame) for frame in frames],
    }


def _print_result(result: dict[str, object]) -> None:
    """Print the workload identity and whole-cycle result before diagnostics."""
    workload = result["workload"]
    summaries = result["summaries"]
    counts = result["counts"]
    sources = result["sources"]
    if not all(
        isinstance(value, dict) for value in (workload, summaries, counts, sources)
    ):
        raise TypeError("invalid benchmark result")
    print(
        f"source.qpane={sources['qpane']}\n"
        f"source.cutecanvas={sources['cutecanvas']}\n"
        f"viewport.logical={workload['logical_width']}x"
        f"{workload['logical_height']} viewport.physical="
        f"{workload['physical_width']}x{workload['physical_height']} "
        f"dpr={workload['device_pixel_ratio']:.3g} zoom={workload['zoom']:g}"
    )
    for name in (
        "pointer_to_present",
        "input_dispatch",
        "event_drain",
        "paint_event",
        "surface_scroll",
        "repair",
        "backing_paint",
        "presentation",
        "repair_pointer_to_present",
    ):
        summary = summaries.get(name)
        if not isinstance(summary, dict) or not summary["count"]:
            continue
        print(
            f"{name:>28}: mean={summary['mean_ms']:8.3f} "
            f"p95={summary['p95_ms']:8.3f} "
            f"p99={summary['p99_ms']:8.3f} "
            f"max={summary['max_ms']:8.3f} ms"
        )
    print(
        f"frames={counts['frames']} repairs={counts['scroll_repairs']} "
        f">30ms={counts['frames_over_target_ms']} "
        f">16.67ms={counts['frames_over_16_67_ms']} "
        f">100ms={counts['frames_over_100_ms']}"
    )
    correctness = result.get("correctness")
    if isinstance(correctness, dict):
        print(
            f"correctness={'PASS' if correctness['passed'] else 'FAIL'} "
            f"checkpoints={len(correctness['checked_steps'])} "
            f"failures={correctness['failure_count']} "
            f"tolerance={correctness['channel_tolerance']} "
            f"exact_differences={correctness['exact_mismatch_checkpoints']} "
            f"max_delta={correctness['max_observed_channel_delta']}"
        )


def _counter_increased(before: object, after: object, name: str) -> bool:
    """Return whether an optional renderer counter increased."""
    return int(getattr(after, name, 0)) > int(getattr(before, name, 0))


def _nearest_rank(ordered: Sequence[float], quantile: float) -> float:
    """Return one nearest-rank quantile from sorted non-empty values."""
    index = min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1)
    return float(ordered[index])


def _sha256(path: Path) -> str:
    """Return the SHA-256 digest of one workload document."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
