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

"""Headless QPane lifecycle and phase measurement for pan profiling."""

from __future__ import annotations

import math
import os
import time
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Self

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QEvent, QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QImage, QPaintEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from qpane import QPane


@dataclass(frozen=True, slots=True)
class PanPerformanceProfile:
    """Describe one reproducible headless navigation workload."""

    name: str
    physical_viewport: QSize
    image_size: QSize
    zoom: float
    steps: int
    warmup_steps: int
    path_cycles: float


@dataclass(frozen=True, slots=True)
class PanFrameTiming:
    """Record end-to-end and nested phase latency for one pointer update."""

    step_index: int
    pointer_x: int
    pointer_y: int
    pan_x: float
    pan_y: float
    end_to_end_ms: float
    input_dispatch_ms: float
    explicit_repaint_ms: float
    event_drain_ms: float
    paint_event_ms: float
    planning_ms: float
    scroll_attempt_ms: float
    surface_scroll_ms: float
    repair_ms: float
    backing_paint_ms: float
    presentation_ms: float
    paint_event_count: int
    scroll_attempted: bool
    scroll_repaired: bool
    full_redraw: bool


@dataclass(slots=True)
class PhaseRecorder:
    """Attribute nested synchronous phase durations to the active pan step."""

    active_step: int | None = None
    _durations: dict[int, dict[str, list[float]]] = field(default_factory=dict)

    def record(self, phase: str, elapsed_ms: float) -> None:
        """Retain one duration only while a measured step is active."""
        step = self.active_step
        if step is None:
            return
        self._durations.setdefault(step, {}).setdefault(phase, []).append(elapsed_ms)

    def total(self, step: int, phase: str) -> float:
        """Return the sum of one nested phase for a measured step."""
        return float(sum(self._durations.get(step, {}).get(phase, ())))

    def count(self, step: int, phase: str) -> int:
        """Return the invocation count of one phase for a measured step."""
        return len(self._durations.get(step, {}).get(phase, ()))


class TimedQPane(QPane):
    """Expose full QWidget paint-event timing to the standalone harness."""

    def __init__(self, recorder: PhaseRecorder) -> None:
        """Create a production QPane with a timing-only observer."""
        self._performance_recorder = recorder
        super().__init__()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Time complete production widget painting for the active pan step."""
        started = time.perf_counter()
        try:
            super().paintEvent(event)
        finally:
            self._performance_recorder.record(
                "paint_event",
                (time.perf_counter() - started) * 1000.0,
            )


class MethodPhaseProbe:
    """Time one replaceable Python method without changing its behavior."""

    def __init__(
        self,
        owner: object,
        method_name: str,
        phase: str,
        recorder: PhaseRecorder,
    ) -> None:
        """Bind a method and the phase label that should receive its duration."""
        self._owner = owner
        self._method_name = method_name
        self._phase = phase
        self._recorder = recorder
        self._original: Callable[..., Any] | None = None

    def __enter__(self) -> Self:
        """Install the transparent timing wrapper."""
        original = getattr(self._owner, self._method_name)
        if not callable(original):
            raise TypeError(f"{self._method_name} must be callable")
        self._original = original

        def measured(*args: object, **kwargs: object) -> Any:
            """Delegate one method call and record its wall duration."""
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


class HeadlessPanPerformanceHarness:
    """Drive an offscreen production QPane through real Qt pointer events."""

    def __init__(
        self,
        application: QApplication,
        profile: PanPerformanceProfile,
        image: QImage,
    ) -> None:
        """Mount the requested workload and settle all initial raster products."""
        if image.isNull():
            raise ValueError("image must be non-null")
        self._application = application
        self._profile = profile
        self._image = QImage(image)
        self._recorder = PhaseRecorder()
        self._pane = TimedQPane(self._recorder)
        self._logical_viewport = QSize()
        self._physical_viewport = QSize()
        self._device_pixel_ratio = 1.0
        self._mount()

    @property
    def pane(self) -> QPane:
        """Return the mounted production viewer."""
        return self._pane

    @property
    def logical_viewport(self) -> QSize:
        """Return the mounted widget size in device-independent pixels."""
        return QSize(self._logical_viewport)

    @property
    def physical_viewport(self) -> QSize:
        """Return the measured viewport size in physical pixels."""
        return QSize(self._physical_viewport)

    @property
    def device_pixel_ratio(self) -> float:
        """Return the device-pixel ratio used by the offscreen viewer."""
        return self._device_pixel_ratio

    def run(self) -> list[PanFrameTiming]:
        """Warm the renderer, drive one measured drag, and return every frame."""
        warmup_path = pointer_path(
            self._pane.size(),
            steps=self._profile.warmup_steps,
            cycles=max(0.5, self._profile.path_cycles / 2.0),
        )
        if warmup_path:
            self._drive_pointer_path(warmup_path, measured=False)
            self._wait_for_render_idle()
            self._pane.setPan(QPointF())
            self._pane.repaint()
            self._application.processEvents()
        measured_path = pointer_path(
            self._pane.size(),
            steps=self._profile.steps,
            cycles=self._profile.path_cycles,
        )
        return self._drive_pointer_path(measured_path, measured=True)

    def close(self) -> None:
        """Release the mounted offscreen widget and drain deferred deletion."""
        self._pane.close()
        self._pane.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self._application.processEvents()

    def _mount(self) -> None:
        """Configure the scene, physical viewport geometry, and initial exact frame."""
        requested = self._profile.physical_viewport
        screen = self._pane.screen()
        initial_dpr = (
            1.0 if screen is None else max(0.01, float(screen.devicePixelRatio()))
        )
        logical = QSize(
            max(1, round(requested.width() / initial_dpr)),
            max(1, round(requested.height() / initial_dpr)),
        )
        self._pane.resize(logical)
        self._pane.applySettings(
            drag_out_enabled=False,
            smooth_zoom_enabled=False,
        )
        self._pane.setImage(self._image, fit=False)
        self._pane.show()
        self._application.processEvents()
        self._device_pixel_ratio = max(0.01, float(self._pane.devicePixelRatioF()))
        corrected_logical = QSize(
            max(1, round(requested.width() / self._device_pixel_ratio)),
            max(1, round(requested.height() / self._device_pixel_ratio)),
        )
        if corrected_logical != self._pane.size():
            self._pane.resize(corrected_logical)
            self._application.processEvents()
        self._pane._rendering.presenter.ensure_view_alignment(force=True)
        self._pane.applyZoom(self._profile.zoom, self._pane.rect().center())
        self._pane.setPan(QPointF())
        self._pane._rendering.presenter.mark_dirty()
        self._pane.repaint()
        self._wait_for_render_idle()
        if not math.isclose(
            self._pane.currentZoom(),
            self._profile.zoom,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            raise RuntimeError(
                "mounted viewer did not retain requested zoom: "
                f"requested={self._profile.zoom:g}, "
                f"actual={self._pane.currentZoom():g}"
            )
        self._logical_viewport = QSize(self._pane.size())
        physical = self._pane.physicalViewportRect().size()
        self._physical_viewport = QSize(
            round(physical.width()),
            round(physical.height()),
        )

    def _drive_pointer_path(
        self,
        positions: Sequence[QPoint],
        *,
        measured: bool,
    ) -> list[PanFrameTiming]:
        """Drive one direct pan gesture and optionally retain per-step timing."""
        if not positions:
            return []
        renderer = self._pane._rendering.presenter.renderer
        presenter = self._pane._rendering.presenter
        surface = renderer._surface
        timings: list[PanFrameTiming] = []
        origin = positions[0]
        probes = (
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
                surface,
                "scroll",
                "surface_scroll",
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
        )
        with ExitStack() as stack:
            for probe in probes:
                stack.enter_context(probe)
            QTest.mousePress(
                self._pane,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                origin,
            )
            try:
                for step_index, position in enumerate(positions[1:]):
                    before = renderer.snapshot_metrics()
                    self._recorder.active_step = step_index if measured else None
                    started = time.perf_counter()
                    QTest.mouseMove(self._pane, position, delay=0)
                    dispatched = time.perf_counter()
                    self._pane.repaint()
                    repainted = time.perf_counter()
                    self._application.processEvents()
                    finished = time.perf_counter()
                    if not measured:
                        continue
                    after = renderer.snapshot_metrics()
                    timings.append(
                        PanFrameTiming(
                            step_index=step_index,
                            pointer_x=position.x(),
                            pointer_y=position.y(),
                            pan_x=self._pane.currentPan().x(),
                            pan_y=self._pane.currentPan().y(),
                            end_to_end_ms=(finished - started) * 1000.0,
                            input_dispatch_ms=(dispatched - started) * 1000.0,
                            explicit_repaint_ms=(repainted - dispatched) * 1000.0,
                            event_drain_ms=(finished - repainted) * 1000.0,
                            paint_event_ms=self._recorder.total(
                                step_index,
                                "paint_event",
                            ),
                            planning_ms=self._recorder.total(step_index, "planning"),
                            scroll_attempt_ms=self._recorder.total(
                                step_index,
                                "scroll_attempt",
                            ),
                            surface_scroll_ms=self._recorder.total(
                                step_index,
                                "surface_scroll",
                            ),
                            repair_ms=self._recorder.total(step_index, "repair"),
                            backing_paint_ms=self._recorder.total(
                                step_index,
                                "backing_paint",
                            ),
                            presentation_ms=self._recorder.total(
                                step_index,
                                "presentation",
                            ),
                            paint_event_count=self._recorder.count(
                                step_index,
                                "paint_event",
                            ),
                            scroll_attempted=after.scroll_attempts
                            > before.scroll_attempts,
                            scroll_repaired=after.scroll_repairs
                            > before.scroll_repairs,
                            full_redraw=after.full_redraws > before.full_redraws,
                        )
                    )
            finally:
                self._recorder.active_step = None
                QTest.mouseRelease(
                    self._pane,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                    positions[-1],
                )
        self._wait_for_render_idle()
        return timings

    def _wait_for_render_idle(self, *, timeout_seconds: float = 8.0) -> None:
        """Wait until raster and navigation refinement remain continuously idle."""
        deadline = time.perf_counter() + timeout_seconds
        idle_since: float | None = None
        view = self._pane._rendering
        while time.perf_counter() < deadline:
            self._application.processEvents()
            tile_metrics = view.presenter.tile_manager.snapshot_metrics()
            idle = (
                not view.pyramids.pending_asset_keys()
                and not view.pyramids.pending_retry_asset_keys()
                and tile_metrics.active_jobs == 0
                and tile_metrics.pending_retries == 0
                and not view.presenter.navigation_refinement_pending
            )
            now = time.perf_counter()
            if idle:
                idle_since = now if idle_since is None else idle_since
                if now - idle_since >= 0.025:
                    return
            else:
                idle_since = None
            QTest.qWait(1)
        raise TimeoutError("pan performance harness did not reach render idle")


def pointer_path(size: QSize, *, steps: int, cycles: float) -> tuple[QPoint, ...]:
    """Return a bounded deterministic path with reversals and guard crossings."""
    if size.isEmpty():
        raise ValueError("pointer path size must be non-empty")
    if steps < 2:
        raise ValueError("pointer path requires at least two steps")
    if cycles <= 0.0:
        raise ValueError("pointer path cycles must be positive")
    center = QPoint(size.width() // 2, size.height() // 2)
    radius_x = max(1.0, size.width() * 0.36)
    radius_y = max(1.0, size.height() * 0.31)
    return tuple(
        center
        + QPoint(
            round(radius_x * math.sin(index * math.tau * cycles / (steps - 1))),
            round(radius_y * math.sin(index * math.tau * cycles * 1.7 / (steps - 1))),
        )
        for index in range(steps)
    )
