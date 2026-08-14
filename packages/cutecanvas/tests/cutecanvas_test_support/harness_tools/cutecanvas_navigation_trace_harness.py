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

"""Replay a recorded CuteCanvas pan/zoom session headlessly with timing."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from pathlib import Path
from types import TracebackType
from typing import Any

from typing_extensions import Self


def _configure_qt_before_imports(arguments: list[str]) -> None:
    """Select offscreen Qt and the trace's recorded DPR before importing PySide."""
    if "-h" in arguments or "--help" in arguments:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        return
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--device-pixel-ratio", type=float)
    parser.add_argument("--tile-size", type=int)
    options, _unknown = parser.parse_known_args(arguments)
    payload = json.loads(options.trace.read_text(encoding="utf-8"))
    device_pixel_ratio = (
        options.device_pixel_ratio
        if options.device_pixel_ratio is not None
        else payload.get("device_pixel_ratio")
    )
    if not isinstance(device_pixel_ratio, (int, float)) or device_pixel_ratio <= 0:
        raise ValueError("navigation trace device_pixel_ratio must be positive")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QT_SCALE_FACTOR"] = str(float(device_pixel_ratio))


if __name__ == "__main__":
    _configure_qt_before_imports(sys.argv[1:])

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPixmap,
    QTransform,
    QWheelEvent,
)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cutecanvas_test_support.harness_tools.cutecanvas_pan_performance_harness import (
    DocumentPanHarness,
    LatencySummary,
    _plan_transforms,
    compare_images,
    save_difference_artifacts,
    summarize_latencies,
)
from demonstration.navigation_trace import (
    NavigationState,
    NavigationTrace,
    NavigationTraceEvent,
    load_navigation_trace,
    sha256_file,
)
from qpane.rendering.navigation_buffer import navigation_buffer_transform
from qpane.rendering.navigation_plan import (
    navigation_products_match,
    retained_raster_navigation_delta,
    translated_navigation_plan,
)
from qpane.scene.render_plan import (
    RasterLayerRenderItem,
    SampledLayerRenderItem,
    SceneRenderPlan,
    VectorLayerRenderItem,
)

_SETTLED_CORRECTNESS_TOLERANCE = 1
_ACTIVE_CORRECTNESS_TOLERANCE = 8
_ACTIVE_SEVERE_TOLERANCE = 64
_ACTIVE_MISMATCH_RATIO_LIMIT = 0.001
_ACTIVE_SEVERE_RATIO_LIMIT = 0.0001
_ACTIVE_SEVERE_MINIMUM_PIXEL_LIMIT = 512
_TARGET_P95_MS = 30.0


@dataclass(frozen=True, slots=True)
class TraceFrameTiming:
    """Record one navigation-producing event and its diagnostic phases."""

    event_index: int
    event_kind: str
    recorded_elapsed_ms: float
    pointer_x: float
    pointer_y: float
    buttons: int
    zoom: float
    pan_x: float
    pan_y: float
    pointer_to_present_ms: float
    input_dispatch_ms: float
    event_drain_ms: float
    paint_event_ms: float
    planning_ms: float
    scroll_attempt_ms: float
    surface_scroll_ms: float
    repair_ms: float
    repair_physical_pixels: int
    backing_paint_ms: float
    presentation_ms: float
    paint_event_count: int
    scroll_attempted: bool
    scroll_repaired: bool
    full_redraw: bool


class RepairAreaProbe:
    """Record physical repair coverage without changing renderer behavior."""

    def __init__(self, replay: NavigationTraceReplay) -> None:
        """Bind the active replay's renderer and phase recorder."""
        self._renderer = replay._canvas.view().presenter.renderer
        self._recorder = replay._recorder
        self._original: object | None = None

    def __enter__(self) -> Self:
        """Install the repair-coverage observer."""
        original = self._renderer._repair_base_buffer_strips
        self._original = original

        def measured(rects: list[QRect], plan: object) -> object:
            """Record total physical pixels submitted for one repair."""
            self._recorder.record(
                "repair_physical_pixels",
                float(sum(rect.width() * rect.height() for rect in rects)),
            )
            return original(rects, plan)

        self._renderer._repair_base_buffer_strips = measured
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Restore the production repair method."""
        del exc_type, exc_value, traceback
        if self._original is not None:
            self._renderer._repair_base_buffer_strips = self._original
            self._original = None


class NavigationTraceReplay:
    """Drive one recorded event stream through a mounted production canvas."""

    def __init__(
        self,
        harness: DocumentPanHarness,
        trace: NavigationTrace,
        *,
        preserve_cadence: bool,
    ) -> None:
        """Bind one trace to a document harness with matching geometry."""
        self._harness = harness
        self._application = harness._application
        self._canvas = harness.canvas
        self._trace = trace
        self._preserve_cadence = preserve_cadence
        self._recorder = harness._recorder
        self._logical_scale_x = self._canvas.width() / trace.logical_width
        self._logical_scale_y = self._canvas.height() / trace.logical_height
        dpr_scale = self._canvas.devicePixelRatioF() / trace.device_pixel_ratio
        self._physical_scale_x = self._logical_scale_x * dpr_scale
        self._physical_scale_y = self._logical_scale_y * dpr_scale
        self._legacy_navigation_mode_inferred = (
            not any(event.kind == "control_mode" for event in trace.events)
            and trace.control_mode != self._canvas.CONTROL_MODE_PANZOOM
            and any(
                event.kind == "wheel" or (event.kind == "mouse_move" and event.buttons)
                for event in trace.events
            )
        )
        self._configure_recorded_navigation()

    def run_timing(self) -> list[TraceFrameTiming]:
        """Replay every event and time each event that presents a frame."""
        self.reset()
        renderer = self._canvas.view().presenter.renderer
        frames: list[TraceFrameTiming] = []
        replay_started_ns = time.perf_counter_ns()
        with ExitStack() as stack:
            for probe in self._harness.phase_probes():
                if probe.available:
                    stack.enter_context(probe)
            stack.enter_context(RepairAreaProbe(self))
            try:
                for event_index, trace_event in enumerate(self._trace.events):
                    self._wait_for_recorded_cadence(trace_event, replay_started_ns)
                    if self._apply_control_mode_event(trace_event):
                        continue
                    before = renderer.snapshot_metrics()
                    self._recorder.active_step = event_index
                    started = time.perf_counter()
                    QApplication.sendEvent(
                        self._canvas,
                        qt_event_from_trace(
                            trace_event,
                            scale_x=self._logical_scale_x,
                            scale_y=self._logical_scale_y,
                        ),
                    )
                    dispatched = time.perf_counter()
                    self._application.processEvents()
                    presented = time.perf_counter()
                    if self._recorder.count(event_index, "paint_event") < 1:
                        continue
                    after = renderer.snapshot_metrics()
                    frames.append(
                        self._frame_timing(
                            event_index,
                            trace_event,
                            before,
                            after,
                            started=started,
                            dispatched=dispatched,
                            presented=presented,
                        )
                    )
            finally:
                self._recorder.active_step = None
        self._harness._wait_for_render_idle()
        return frames

    def run_correctness(
        self,
        frames: list[TraceFrameTiming],
        *,
        checkpoint_limit: int,
        checkpoint_events: tuple[int, ...] = (),
        artifact_root: Path,
    ) -> dict[str, Any]:
        """Compare retained pan frames with independent full-resolution composition."""
        del frames
        checkpoints = (
            set(checkpoint_events)
            if checkpoint_events
            else _pan_checkpoint_event_indices(
                self._trace.events,
                checkpoint_limit,
            )
        )
        self.reset()
        failures: list[dict[str, Any]] = []
        exact_difference_count = 0
        maximum_channel_delta = 0
        renderer = self._canvas.view().presenter.renderer
        for checkpoint_index, checkpoint in enumerate(sorted(checkpoints)):
            if checkpoint_index:
                self.reset()
            replay_started_ns = time.perf_counter_ns()
            previous_plan: SceneRenderPlan | None = None
            for event_index, trace_event in enumerate(self._trace.events):
                if event_index > checkpoint:
                    break
                self._wait_for_recorded_cadence(trace_event, replay_started_ns)
                if self._apply_control_mode_event(trace_event):
                    continue
                if event_index == checkpoint:
                    previous_plan = renderer.get_current_render_plan()
                QApplication.sendEvent(
                    self._canvas,
                    qt_event_from_trace(
                        trace_event,
                        scale_x=self._logical_scale_x,
                        scale_y=self._logical_scale_y,
                    ),
                )
                self._application.processEvents()
            checkpoint_event = self._trace.events[checkpoint]
            settled_checkpoint = checkpoint_event.kind == "mouse_release"
            if settled_checkpoint:
                self._harness._wait_for_render_idle()
            plan = renderer.get_current_render_plan()
            if plan is None:
                raise RuntimeError("navigation checkpoint has no render plan")
            incremental_base = renderer.get_base_buffer()
            if incremental_base is None:
                raise RuntimeError("navigation checkpoint has no retained buffer")
            incremental_state = _renderer_navigation_state(renderer)
            incremental_base_frame = _visible_base_frame(
                incremental_base,
                QPointF(),
                renderer._viewport_physical_size,
                renderer.buffer_overscan_physical_px,
            )
            incremental = _presented_base_frame(renderer)
            buffer_plan = getattr(renderer, "_buffer_render_plan", None) or plan
            clean_base = _compose_independent_base_buffer(renderer, buffer_plan)
            clean_base_frame = _visible_base_frame(
                clean_base,
                QPointF(),
                renderer._viewport_physical_size,
                renderer.buffer_overscan_physical_px,
            )
            clean = _present_independent_buffer(
                renderer,
                clean_base,
                buffer_plan=buffer_plan,
                current_plan=plan,
            )
            translation_difference = _independent_translation_difference(
                renderer,
                previous_plan,
                plan,
            )
            channel_tolerance = (
                _SETTLED_CORRECTNESS_TOLERANCE
                if settled_checkpoint
                else _ACTIVE_CORRECTNESS_TOLERANCE
            )
            difference = compare_images(
                incremental,
                clean,
                channel_tolerance=channel_tolerance,
            )
            base_difference = compare_images(
                incremental_base_frame,
                clean_base_frame,
                channel_tolerance=channel_tolerance,
            )
            severe_difference = compare_images(
                incremental,
                clean,
                channel_tolerance=_ACTIVE_SEVERE_TOLERANCE,
            )
            severe_base_difference = compare_images(
                incremental_base_frame,
                clean_base_frame,
                channel_tolerance=_ACTIVE_SEVERE_TOLERANCE,
            )
            maximum_channel_delta = max(
                maximum_channel_delta,
                int(difference["max_channel_delta"]),
                int(base_difference["max_channel_delta"]),
            )
            if (
                difference["exact_mismatch_pixels"]
                or base_difference["exact_mismatch_pixels"]
            ):
                exact_difference_count += 1
            physical_pixels = max(
                1,
                renderer._viewport_physical_size.width()
                * renderer._viewport_physical_size.height(),
            )
            if not (
                _checkpoint_difference_is_acceptable(
                    difference,
                    severe_difference,
                    settled=settled_checkpoint,
                    physical_pixels=physical_pixels,
                )
                and _checkpoint_difference_is_acceptable(
                    base_difference,
                    severe_base_difference,
                    settled=settled_checkpoint,
                    physical_pixels=physical_pixels,
                )
            ):
                directory = artifact_root / f"event-{checkpoint:05d}"
                save_difference_artifacts(directory, incremental, clean)
                save_difference_artifacts(
                    directory / "base",
                    incremental_base_frame,
                    clean_base_frame,
                )
                failures.append(
                    {
                        "event_index": checkpoint,
                        "settled_checkpoint": settled_checkpoint,
                        "artifact_directory": str(directory.resolve()),
                        "visible_difference": difference,
                        "base_difference": base_difference,
                        "severe_visible_difference": severe_difference,
                        "severe_base_difference": severe_base_difference,
                        "plan_transforms": _plan_transforms(plan),
                        "plan_products": _plan_product_snapshot(plan),
                        "plan_presentation_effects": [
                            {
                                "layer_id": str(effect.layer_id),
                                "kind": effect.style.kind.value,
                                "opacity": effect.style.opacity,
                            }
                            for effect in plan.presentation_effects
                        ],
                        "plan_transient_raster": (
                            None
                            if plan.transient_raster is None
                            else type(plan.transient_raster).__name__
                        ),
                        "buffer_plan_products": _plan_product_snapshot(
                            getattr(renderer, "_buffer_render_plan", None)
                        ),
                        "incremental_renderer_state": incremental_state,
                        "independent_translation_difference": (translation_difference),
                    }
                )
        return {
            "passed": not failures,
            "checked_event_indices": sorted(checkpoints),
            "failure_count": len(failures),
            "first_failure": None if not failures else failures[0],
            "settled_channel_tolerance": _SETTLED_CORRECTNESS_TOLERANCE,
            "active_channel_tolerance": _ACTIVE_CORRECTNESS_TOLERANCE,
            "active_mismatch_ratio_limit": _ACTIVE_MISMATCH_RATIO_LIMIT,
            "active_severe_channel_tolerance": _ACTIVE_SEVERE_TOLERANCE,
            "active_severe_ratio_limit": _ACTIVE_SEVERE_RATIO_LIMIT,
            "active_severe_minimum_pixel_limit": (_ACTIVE_SEVERE_MINIMUM_PIXEL_LIMIT),
            "exact_difference_checkpoints": exact_difference_count,
            "max_observed_channel_delta": maximum_channel_delta,
        }

    def _freeze_zoom_frame(self) -> None:
        """Stop interpolation so both checkpoint renders use one navigation state."""
        viewport = self._canvas.view().viewport
        stop_animation = getattr(viewport, "_stop_zoom_animation", None)
        if not callable(stop_animation):
            raise TypeError("viewport must expose zoom-animation cancellation")
        stop_animation()

    def reset(self, *, wait_for_idle: bool = True) -> None:
        """Restore initial viewport state, optionally waiting for derived work."""
        presenter = self._canvas.view().presenter
        presenter.finish_navigation_interaction()
        presenter.renderer.cancel_navigation_refinement()
        state = self._scaled_state(self._trace.initial_state)
        control_mode = (
            self._canvas.CONTROL_MODE_PANZOOM
            if self._legacy_navigation_mode_inferred
            else self._trace.control_mode
        )
        self._canvas.setControlMode(control_mode)
        self._canvas.applyZoom(state.zoom, self._canvas.rect().center())
        self._canvas.setPan(QPointF(state.pan_x, state.pan_y))
        self._harness._force_clean_redraw()
        if wait_for_idle:
            self._harness._wait_for_render_idle()

    @property
    def legacy_navigation_mode_inferred(self) -> bool:
        """Return whether replay repaired a pre-mode-transition capture."""
        return self._legacy_navigation_mode_inferred

    def final_state(self) -> NavigationState:
        """Return the replay's current navigation state."""
        pan = self._canvas.getPan()
        return NavigationState(
            zoom=float(self._canvas.currentZoom()),
            pan_x=pan.x(),
            pan_y=pan.y(),
        )

    def expected_final_state(self) -> NavigationState:
        """Return the recorded terminal state projected into replay geometry."""
        return self._scaled_state(self._trace.final_state)

    def _configure_recorded_navigation(self) -> None:
        """Apply the settings that interpreted the original input stream."""
        settings = dict(self._trace.navigation_settings)
        if (
            settings.get("smooth_zoom_use_display_fps") is True
            and self._trace.screen_refresh_hz > 0.0
        ):
            settings["smooth_zoom_use_display_fps"] = False
            settings["smooth_zoom_fallback_fps"] = self._trace.screen_refresh_hz
        if settings:
            self._canvas.applySettings(**settings)

    def _scaled_state(self, state: NavigationState) -> NavigationState:
        """Project physical pan coordinates into the target viewport and DPR."""
        return NavigationState(
            zoom=state.zoom,
            pan_x=state.pan_x * self._physical_scale_x,
            pan_y=state.pan_y * self._physical_scale_y,
        )

    def _apply_control_mode_event(self, trace_event: NavigationTraceEvent) -> bool:
        """Apply one recorded effective-tool transition outside Qt input delivery."""
        if trace_event.kind != "control_mode":
            return False
        self._canvas.setControlMode(trace_event.control_mode)
        self._application.processEvents()
        return True

    def _wait_for_recorded_cadence(
        self,
        trace_event: NavigationTraceEvent,
        replay_started_ns: int,
    ) -> None:
        """Let the Qt loop advance until one event's recorded delivery time."""
        if not self._preserve_cadence:
            return
        target_ns = replay_started_ns + trace_event.elapsed_ns
        while True:
            remaining_ns = target_ns - time.perf_counter_ns()
            if remaining_ns <= 0:
                return
            QTest.qWait(max(1, min(10, math.ceil(remaining_ns / 1_000_000))))

    def _frame_timing(
        self,
        event_index: int,
        trace_event: NavigationTraceEvent,
        before: object,
        after: object,
        *,
        started: float,
        dispatched: float,
        presented: float,
    ) -> TraceFrameTiming:
        """Build one immutable measured-frame record."""
        pan = self._canvas.getPan()
        return TraceFrameTiming(
            event_index=event_index,
            event_kind=trace_event.kind,
            recorded_elapsed_ms=trace_event.elapsed_ns / 1_000_000.0,
            pointer_x=trace_event.local_x,
            pointer_y=trace_event.local_y,
            buttons=trace_event.buttons,
            zoom=float(self._canvas.currentZoom()),
            pan_x=pan.x(),
            pan_y=pan.y(),
            pointer_to_present_ms=(presented - started) * 1000.0,
            input_dispatch_ms=(dispatched - started) * 1000.0,
            event_drain_ms=(presented - dispatched) * 1000.0,
            paint_event_ms=self._recorder.total(event_index, "paint_event"),
            planning_ms=self._recorder.total(event_index, "planning"),
            scroll_attempt_ms=self._recorder.total(event_index, "scroll_attempt"),
            surface_scroll_ms=self._recorder.total(event_index, "surface_scroll"),
            repair_ms=self._recorder.total(event_index, "repair"),
            repair_physical_pixels=round(
                self._recorder.total(event_index, "repair_physical_pixels")
            ),
            backing_paint_ms=self._recorder.total(event_index, "backing_paint"),
            presentation_ms=self._recorder.total(event_index, "presentation"),
            paint_event_count=self._recorder.count(event_index, "paint_event"),
            scroll_attempted=_counter_increased(before, after, "scroll_attempts"),
            scroll_repaired=_counter_increased(before, after, "scroll_repairs"),
            full_redraw=_counter_increased(before, after, "full_redraws"),
        )


def qt_event_from_trace(
    event: NavigationTraceEvent,
    *,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
) -> QEvent:
    """Rebuild one detached trace event at the requested logical geometry."""
    local = QPointF(event.local_x * scale_x, event.local_y * scale_y)
    global_position = QPointF(
        event.global_x * scale_x,
        event.global_y * scale_y,
    )
    modifiers = Qt.KeyboardModifier(event.modifiers)
    source = Qt.MouseEventSource(event.source)
    if event.kind in {"mouse_press", "mouse_move", "mouse_release"}:
        event_types = {
            "mouse_press": QEvent.Type.MouseButtonPress,
            "mouse_move": QEvent.Type.MouseMove,
            "mouse_release": QEvent.Type.MouseButtonRelease,
        }
        return QMouseEvent(
            event_types[event.kind],
            local,
            local,
            global_position,
            Qt.MouseButton(event.button),
            Qt.MouseButton(event.buttons),
            modifiers,
            source,
        )
    if event.kind == "wheel":
        return QWheelEvent(
            local,
            global_position,
            QPoint(event.pixel_delta_x, event.pixel_delta_y),
            QPoint(event.angle_delta_x, event.angle_delta_y),
            Qt.MouseButton(event.buttons),
            modifiers,
            Qt.ScrollPhase(event.phase),
            event.inverted,
            source,
        )
    event_type = (
        QEvent.Type.KeyPress if event.kind == "key_press" else QEvent.Type.KeyRelease
    )
    return QKeyEvent(
        event_type,
        event.key,
        modifiers,
        "",
        event.auto_repeat,
        1,
    )


def _build_summaries(
    frames: list[TraceFrameTiming],
) -> dict[str, LatencySummary | None]:
    """Summarize primary and diagnostic replay phases."""
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
    return {
        name: summarize_latencies(
            [float(getattr(frame, f"{name}_ms")) for frame in frames]
        )
        for name in names
    }


def _pan_frames(frames: list[TraceFrameTiming]) -> list[TraceFrameTiming]:
    """Return presented left-drag frames without wheel-zoom contamination."""
    left_button = int(Qt.MouseButton.LeftButton.value)
    return [
        frame
        for frame in frames
        if frame.event_kind == "mouse_move" and bool(frame.buttons & left_button)
    ]


def _pan_checkpoint_event_indices(
    events: tuple[NavigationTraceEvent, ...],
    limit: int,
) -> set[int]:
    """Select representative active moves and releases from recorded pans."""
    pan_active = False
    pan_moved = False
    active_moves: list[int] = []
    releases: list[int] = []
    left_button = int(Qt.MouseButton.LeftButton.value)
    for event_index, event in enumerate(events):
        if event.kind == "mouse_press" and event.button == left_button:
            pan_active = True
            pan_moved = False
            continue
        if (
            pan_active
            and event.kind == "mouse_move"
            and bool(event.buttons & left_button)
        ):
            pan_moved = True
            active_moves.append(event_index)
            continue
        if event.kind != "mouse_release" or event.button != left_button:
            continue
        if pan_active and pan_moved:
            releases.append(event_index)
        pan_active = False
        pan_moved = False
    if limit <= 0 or not (active_moves or releases):
        return set()
    release_limit = min(len(releases), max(1, limit // 2))
    active_limit = min(len(active_moves), limit - release_limit)
    if active_limit == 0 and active_moves:
        active_limit = 1
        release_limit = max(0, release_limit - 1)
    return _evenly_spaced_indices(active_moves, active_limit) | _evenly_spaced_indices(
        releases,
        release_limit,
    )


def _checkpoint_difference_is_acceptable(
    difference: dict[str, object],
    severe_difference: dict[str, object],
    *,
    settled: bool,
    physical_pixels: int,
) -> bool:
    """Reject any settled drift and structurally meaningful active-pan drift."""
    mismatch_pixels = int(difference["mismatch_pixels"])
    if settled:
        return mismatch_pixels == 0
    ordinary_limit = max(
        1,
        round(max(1, physical_pixels) * _ACTIVE_MISMATCH_RATIO_LIMIT),
    )
    severe_limit = max(
        _ACTIVE_SEVERE_MINIMUM_PIXEL_LIMIT,
        round(max(1, physical_pixels) * _ACTIVE_SEVERE_RATIO_LIMIT),
    )
    return (
        mismatch_pixels <= ordinary_limit
        and int(severe_difference["mismatch_pixels"]) <= severe_limit
    )


def _evenly_spaced_indices(candidates: list[int], limit: int) -> set[int]:
    """Return up to ``limit`` indices distributed across one chronology."""
    if limit <= 0 or not candidates:
        return set()
    if len(candidates) <= limit:
        return set(candidates)
    return {
        candidates[round(slot * (len(candidates) - 1) / max(1, limit - 1))]
        for slot in range(limit)
    }


def _state_difference(
    actual: NavigationState,
    expected: NavigationState,
) -> dict[str, float | bool]:
    """Report replay drift from the state recorded when capture stopped."""
    zoom_delta = actual.zoom - expected.zoom
    pan_x_delta = actual.pan_x - expected.pan_x
    pan_y_delta = actual.pan_y - expected.pan_y
    return {
        "zoom_delta": zoom_delta,
        "pan_x_delta": pan_x_delta,
        "pan_y_delta": pan_y_delta,
        "matches": (
            math.isclose(zoom_delta, 0.0, abs_tol=1e-9)
            and math.isclose(pan_x_delta, 0.0, abs_tol=1e-6)
            and math.isclose(pan_y_delta, 0.0, abs_tol=1e-6)
        ),
    }


def _renderer_navigation_state(renderer: object) -> dict[str, object]:
    """Return serializable retained-frame geometry for one checkpoint."""

    def point(value: object) -> list[float]:
        """Detach a Qt point into two JSON scalars."""
        return [float(value.x()), float(value.y())]

    def transform_values(transform: QTransform) -> list[float]:
        """Detach one projective transform into Qt's stable matrix order."""
        return [
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

    surface = getattr(renderer, "_surface", None)
    storage_origin = (
        QPoint() if surface is None else getattr(surface, "storage_origin", QPoint())
    )
    current_plan = renderer.get_current_render_plan()
    buffer_plan = getattr(renderer, "_buffer_render_plan", None)
    refinement_metrics = renderer.navigation_refinement_metrics()
    return {
        "buffer_pan": point(getattr(renderer, "_buffer_pan", QPointF())),
        "current_pan": (
            point(current_plan.current_pan) if current_plan is not None else None
        ),
        "buffer_plan_pan": (
            point(buffer_plan.current_pan) if buffer_plan is not None else None
        ),
        "subpixel_pan_offset": point(renderer.get_subpixel_pan_offset()),
        "presentation_transform": transform_values(
            getattr(renderer, "_presentation_transform", QTransform())
        ),
        "storage_origin": point(storage_origin),
        "buffer_overscan_physical_px": int(renderer.buffer_overscan_physical_px),
        "buffer_products_match_current": (
            current_plan is not None
            and buffer_plan is not None
            and navigation_products_match(buffer_plan, current_plan)
        ),
        "staged_completed_frames": refinement_metrics.completed_frames,
        "staged_cancelled_frames": refinement_metrics.cancelled_frames,
    }


def _plan_product_snapshot(
    plan: SceneRenderPlan | None,
) -> list[dict[str, object]]:
    """Return serializable resolved-product identity for one render plan."""
    if plan is None:
        return []
    products: list[dict[str, object]] = []
    for item in plan.render_items:
        product: dict[str, object] = {
            "type": type(item).__name__,
            "layer_id": str(item.descriptor.layer_id),
            "visible": item.descriptor.visible,
            "opacity": item.descriptor.opacity,
        }
        if isinstance(item, RasterLayerRenderItem):
            product.update(
                {
                    "strategy": item.strategy.value,
                    "source_cache_key": item.source_image.cacheKey(),
                    "source_size": [
                        item.source_image.width(),
                        item.source_image.height(),
                    ],
                    "pyramid_asset_key": repr(item.pyramid_asset_key),
                    "pyramid_scale": item.pyramid_scale,
                    "tiles": [
                        {
                            "cache_key": tile.image.cacheKey(),
                            "draw_pos": [tile.draw_pos.x(), tile.draw_pos.y()],
                        }
                        for tile in item.tiles_to_draw
                    ],
                }
            )
        elif isinstance(item, SampledLayerRenderItem):
            product.update(
                {
                    "source_size": [
                        item.source_size.width(),
                        item.source_size.height(),
                    ],
                    "tiles": [
                        {
                            "cache_key": tile.image.cacheKey(),
                            "source_rect": _rect_values(tile.source_rect),
                            "image_source_rect": _rect_values(tile.image_source_rect),
                        }
                        for tile in item.tiles
                    ],
                }
            )
        elif isinstance(item, VectorLayerRenderItem):
            product.update(
                {
                    "picture_size": len(bytes(item.picture.data() or b"")),
                    "refined_tiles": [
                        {
                            "cache_key": tile.image.cacheKey(),
                            "source_rect": _rect_values(tile.source_rect),
                            "image_source_rect": _rect_values(tile.image_source_rect),
                        }
                        for tile in item.refined_tiles
                    ],
                }
            )
        products.append(product)
    return products


def _rect_values(rect: object) -> list[float]:
    """Detach one Qt rectangle into JSON scalars."""
    return [
        float(rect.x()),
        float(rect.y()),
        float(rect.width()),
        float(rect.height()),
    ]


def _visible_base_frame(
    base_buffer: QImage,
    subpixel_offset: QPointF,
    viewport_size: QSize,
    overscan_margin: int,
) -> QImage:
    """Return the viewport crop from one linear retained-buffer snapshot."""
    frame = QImage(viewport_size, QImage.Format.Format_ARGB32_Premultiplied)
    frame.setDevicePixelRatio(base_buffer.devicePixelRatio())
    frame.fill(Qt.GlobalColor.transparent)
    device_pixel_ratio = max(0.01, base_buffer.devicePixelRatio())
    painter = QPainter(frame)
    try:
        painter.drawImage(
            QPointF(
                (-float(overscan_margin) + subpixel_offset.x()) / device_pixel_ratio,
                (-float(overscan_margin) + subpixel_offset.y()) / device_pixel_ratio,
            ),
            base_buffer,
        )
    finally:
        painter.end()
    return frame


def _presented_base_frame(renderer: object) -> QImage:
    """Render the retained presentation without triggering a widget repaint."""
    viewport_size = renderer._viewport_physical_size
    base_buffer = renderer.get_base_buffer()
    if base_buffer is None:
        raise RuntimeError("renderer has no retained base buffer")
    frame = QImage(viewport_size, QImage.Format.Format_ARGB32_Premultiplied)
    frame.setDevicePixelRatio(base_buffer.devicePixelRatio())
    frame.fill(Qt.GlobalColor.transparent)
    painter = QPainter(frame)
    try:
        renderer.draw_base_buffer(painter)
    finally:
        painter.end()
    return frame


def _present_independent_buffer(
    renderer: object,
    buffer_image: QImage,
    *,
    buffer_plan: SceneRenderPlan,
    current_plan: SceneRenderPlan,
) -> QImage:
    """Present canonical buffer pixels through the renderer's active geometry."""
    viewport_size = renderer._viewport_physical_size
    frame = QImage(viewport_size, QImage.Format.Format_ARGB32_Premultiplied)
    frame.setDevicePixelRatio(buffer_image.devicePixelRatio())
    frame.fill(Qt.GlobalColor.transparent)
    presentation = QPixmap.fromImage(buffer_image)
    if math.isclose(
        buffer_plan.zoom,
        current_plan.zoom,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        presentation_transform = QTransform()
        physical_delta = retained_raster_navigation_delta(
            buffer_plan,
            current_plan,
            device_pixel_ratio=buffer_image.devicePixelRatio(),
        )
        subpixel_pan_offset = (
            renderer.get_subpixel_pan_offset()
            if physical_delta is None
            else QPointF(physical_delta)
        )
    else:
        presentation_transform = navigation_buffer_transform(
            buffer_plan,
            current_plan,
            overscan=renderer.buffer_overscan_physical_px,
            device_pixel_ratio=buffer_image.devicePixelRatio(),
        )
        subpixel_pan_offset = QPointF()
    painter = QPainter(frame)
    try:
        painter.setClipRegion(renderer._presentation_content_region())
        renderer._frame_presenter.draw(
            painter,
            presentation,
            viewport_physical_size=viewport_size,
            viewport_rect=renderer.qpane.rect(),
            overscan_physical_px=renderer.buffer_overscan_physical_px,
            subpixel_pan_offset=subpixel_pan_offset,
            presentation_transform=presentation_transform,
        )
    finally:
        painter.end()
    return frame


def _compose_independent_base_buffer(
    renderer: object,
    plan: SceneRenderPlan,
) -> QImage:
    """Compose a detached canonical surface from one immutable render plan."""
    source = renderer._surface.pixmap
    composed = QPixmap(source.size())
    composed.setDevicePixelRatio(source.devicePixelRatio())
    composed.fill(Qt.GlobalColor.transparent)
    physical_rects = (QRect(source.rect()),)
    base_only_item = renderer._base_only_raster_item(plan)

    def draw(
        painter: QPainter,
        panel_clips: tuple[QRectF, ...],
    ) -> None:
        """Draw the plan through its source-neutral compositor contract."""
        if base_only_item is not None:
            renderer._items.draw_raster_item(
                painter,
                plan,
                base_only_item,
                panel_clips=panel_clips,
            )
            return
        renderer._items.draw_visible_items(
            painter,
            plan,
            panel_clips=panel_clips,
        )

    for physical_rect in physical_rects:
        painter = QPainter(composed)
        try:
            renderer._patch_painter.paint(
                painter,
                (physical_rect,),
                draw,
            )
        finally:
            painter.end()
    return composed.toImage()


def _independent_translation_difference(
    renderer: object,
    previous_plan: SceneRenderPlan | None,
    current_plan: SceneRenderPlan,
) -> dict[str, object] | None:
    """Compare independently composed adjacent plans over their retained overlap."""
    if previous_plan is None:
        return None
    source = renderer._surface.pixmap
    stable_product_plan = translated_navigation_plan(
        previous_plan,
        current_plan.current_pan,
        device_pixel_ratio=source.devicePixelRatio(),
    )
    stable_product_difference = _translated_plan_difference(
        renderer,
        previous_plan,
        stable_product_plan,
    )
    actual_difference = _translated_plan_difference(
        renderer,
        previous_plan,
        current_plan,
    )
    return {
        "products_match": navigation_products_match(
            previous_plan,
            current_plan,
        ),
        "stable_product_difference": stable_product_difference,
        "actual_plan_difference": actual_difference,
    }


def _translated_plan_difference(
    renderer: object,
    previous_plan: SceneRenderPlan,
    current_plan: SceneRenderPlan,
) -> dict[str, object]:
    """Compare two independently composed plans over one translated overlap."""
    source = renderer._surface.pixmap
    physical_delta = retained_raster_navigation_delta(
        previous_plan,
        current_plan,
        device_pixel_ratio=source.devicePixelRatio(),
    )
    if physical_delta is None:
        return {
            "reusable_translation": False,
            "products_match": navigation_products_match(
                previous_plan,
                current_plan,
            ),
        }
    previous = _compose_independent_base_buffer(renderer, previous_plan)
    current = _compose_independent_base_buffer(renderer, current_plan)
    overlap = source.rect().translated(physical_delta).intersected(source.rect())
    previous_overlap = previous.copy(overlap.translated(-physical_delta))
    current_overlap = current.copy(overlap)
    difference = compare_images(
        previous_overlap,
        current_overlap,
        channel_tolerance=_ACTIVE_CORRECTNESS_TOLERANCE,
    )
    return {
        "reusable_translation": True,
        "products_match": navigation_products_match(
            previous_plan,
            current_plan,
        ),
        "physical_delta": [physical_delta.x(), physical_delta.y()],
        "overlap": _rect_values(overlap),
        "previous_plan_transforms": _plan_transforms(previous_plan),
        "current_plan_transforms": _plan_transforms(current_plan),
        "difference": difference,
    }


def _counter_increased(before: object, after: object, name: str) -> bool:
    """Return whether one renderer metric increased."""
    return int(getattr(after, name, 0)) > int(getattr(before, name, 0))


def _parse_args(arguments: list[str]) -> argparse.Namespace:
    """Parse trace replay inputs and artifact destinations."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--document", type=Path)
    parser.add_argument("--logical-width", type=int)
    parser.add_argument("--logical-height", type=int)
    parser.add_argument("--device-pixel-ratio", type=float)
    parser.add_argument("--tile-size", type=int)
    parser.add_argument("--no-cadence", action="store_true")
    parser.add_argument("--no-correctness", action="store_true")
    parser.add_argument("--correctness-steps", type=int, default=10)
    parser.add_argument(
        "--correctness-event",
        action="append",
        type=int,
        default=[],
        help="Replay only this exact settled checkpoint; may be repeated.",
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("pan-performance-artifacts") / "navigation-trace",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args(arguments)


def _resolve_document(
    options: argparse.Namespace,
    trace: NavigationTrace,
) -> Path:
    """Resolve and verify the composition bound to a trace."""
    path = options.document
    if path is None and trace.document_path:
        path = Path(trace.document_path)
    if path is None:
        raise ValueError("--document is required when the trace has no document path")
    # The replay harness intentionally consumes its operator-selected local document.
    # codeql[py/path-injection]
    document = path.resolve()
    # The resolved path is only admitted as an existing regular local file.
    # codeql[py/path-injection]
    if not document.is_file():
        raise FileNotFoundError(document)
    digest = sha256_file(document)
    if trace.document_sha256 and digest != trace.document_sha256:
        raise ValueError(
            "trace document hash mismatch: "
            f"recorded={trace.document_sha256} current={digest}"
        )
    return document


def _print_summaries(summaries: dict[str, LatencySummary | None]) -> None:
    """Print compact replay timing summaries."""
    for name, summary in summaries.items():
        if summary is None:
            continue
        print(
            f"{name:>28}: mean={summary.mean_ms:8.3f} "
            f"p95={summary.p95_ms:8.3f} max={summary.max_ms:8.3f} ms"
        )


def main(arguments: list[str] | None = None) -> int:
    """Replay one captured session through the production offscreen canvas."""
    options = _parse_args(list(arguments) if arguments is not None else sys.argv[1:])
    trace = load_navigation_trace(options.trace)
    document = _resolve_document(options, trace)
    logical_width = options.logical_width or trace.logical_width
    logical_height = options.logical_height or trace.logical_height
    requested_dpr = options.device_pixel_ratio or trace.device_pixel_ratio
    if logical_width <= 0 or logical_height <= 0:
        raise ValueError("replay viewport dimensions must be positive")
    if requested_dpr <= 0.0:
        raise ValueError("replay device-pixel ratio must be positive")
    application = QApplication.instance() or QApplication(sys.argv[:1])
    if application.platformName().lower() != "offscreen":
        raise RuntimeError("navigation trace replay requires offscreen Qt")
    harness = DocumentPanHarness(
        application,
        document,
        logical_viewport=QSize(logical_width, logical_height),
        zoom=trace.initial_state.zoom,
        steps=4,
        radius_x=1,
        radius_y=1,
        tile_size=options.tile_size,
    )
    try:
        actual_dpr = harness.canvas.devicePixelRatioF()
        if not math.isclose(
            actual_dpr,
            requested_dpr,
            rel_tol=0.0,
            abs_tol=1e-6,
        ):
            raise RuntimeError(
                "headless DPR does not match trace: "
                f"requested={requested_dpr:g} actual={actual_dpr:g}"
            )
        replay = NavigationTraceReplay(
            harness,
            trace,
            preserve_cadence=not options.no_cadence,
        )
        frames = replay.run_timing()
        summaries = _build_summaries(frames)
        pan_frames = _pan_frames(frames)
        pan_summaries = _build_summaries(pan_frames)
        all_navigation = summaries["pointer_to_present"]
        primary = pan_summaries["pointer_to_present"]
        if all_navigation is None:
            raise RuntimeError("trace replay presented no measured navigation frames")
        if primary is None:
            raise RuntimeError("trace replay presented no measured pan frames")
        final_state = replay.final_state()
        expected_final_state = replay.expected_final_state()
        result: dict[str, Any] = {
            "workload": {
                "trace": str(options.trace.resolve()),
                "document": str(document),
                "logical_viewport": [
                    logical_width,
                    logical_height,
                ],
                "physical_viewport": [
                    round(logical_width * actual_dpr),
                    round(logical_height * actual_dpr),
                ],
                "device_pixel_ratio": actual_dpr,
                "tile_size": harness.canvas.view().tile_manager.tile_size,
                "screen_refresh_hz": trace.screen_refresh_hz,
                "recorded_events": len(trace.events),
                "presented_frames": len(frames),
                "preserved_cadence": not options.no_cadence,
                "legacy_navigation_mode_inferred": (
                    replay.legacy_navigation_mode_inferred
                ),
            },
            "summaries": {
                name: None if summary is None else asdict(summary)
                for name, summary in summaries.items()
            },
            "pan_summaries": {
                name: None if summary is None else asdict(summary)
                for name, summary in pan_summaries.items()
            },
            "target": {
                "workload": "left-button mouse-move pan frames",
                "p95_below_30_ms": primary.p95_ms < _TARGET_P95_MS,
                "frames_over_30_ms": sum(
                    frame.pointer_to_present_ms >= _TARGET_P95_MS
                    for frame in pan_frames
                ),
            },
            "recorded_final_state": asdict(trace.final_state),
            "expected_final_state": asdict(expected_final_state),
            "replayed_final_state": asdict(final_state),
            "final_state_difference": _state_difference(
                final_state,
                expected_final_state,
            ),
            "frames": [asdict(frame) for frame in frames],
        }
        if not options.no_correctness:
            result["correctness"] = replay.run_correctness(
                frames,
                checkpoint_limit=options.correctness_steps,
                checkpoint_events=tuple(options.correctness_event),
                artifact_root=options.artifact_root,
            )
        print(
            f"trace={options.trace.resolve()} events={len(trace.events)} "
            f"presented={len(frames)}"
        )
        print(
            f"viewport.logical={logical_width}x{logical_height} "
            f"viewport.physical={round(logical_width * actual_dpr)}x"
            f"{round(logical_height * actual_dpr)} dpr={actual_dpr:g}"
        )
        _print_summaries(summaries)
        print(f"pan.presented={len(pan_frames)}")
        _print_summaries(pan_summaries)
        print(
            f"target.p95_below_30_ms={primary.p95_ms < _TARGET_P95_MS} "
            f"frames_over_30_ms={result['target']['frames_over_30_ms']}"
        )
        correctness = result.get("correctness")
        if isinstance(correctness, dict):
            print(
                f"correctness={'PASS' if correctness['passed'] else 'FAIL'} "
                f"checkpoints={len(correctness['checked_event_indices'])} "
                f"max_delta={correctness['max_observed_channel_delta']}"
            )
        if options.output is not None:
            options.output.parent.mkdir(parents=True, exist_ok=True)
            options.output.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(f"JSON: {options.output.resolve()}")
        return int(isinstance(correctness, dict) and correctness.get("passed") is False)
    finally:
        harness.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
