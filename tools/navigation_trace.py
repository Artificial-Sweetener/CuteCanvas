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

"""Record and validate replayable Qt pan/zoom input traces."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from PySide6.QtCore import QEvent, QObject, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent

TRACE_FORMAT_VERSION = 1
_NAVIGATION_SETTING_NAMES = (
    "smooth_zoom_enabled",
    "smooth_zoom_duration_ms",
    "smooth_zoom_burst_duration_ms",
    "smooth_zoom_burst_threshold_ms",
    "smooth_zoom_fallback_fps",
    "smooth_zoom_use_display_fps",
    "touch_navigation_enabled",
    "palm_rejection_ms",
    "touch_inertia_enabled",
    "touch_inertia_deceleration",
)


class NavigationTraceCanvas(Protocol):
    """Describe the public widget state required by the trace recorder."""

    def devicePixelRatioF(self) -> float:
        """Return the widget's active device-pixel ratio."""

    def getControlMode(self) -> str:
        """Return the active input control mode."""

    def getPan(self) -> QPointF:
        """Return the current viewport pan."""

    def currentZoom(self) -> float:
        """Return the current viewport zoom."""

    def installEventFilter(self, filter_object: QObject) -> None:
        """Install one Qt event filter."""

    def removeEventFilter(self, filter_object: QObject) -> None:
        """Remove one Qt event filter."""

    def width(self) -> int:
        """Return the logical widget width."""

    def height(self) -> int:
        """Return the logical widget height."""


@dataclass(frozen=True, slots=True)
class NavigationState:
    """Capture one viewport navigation state."""

    zoom: float
    pan_x: float
    pan_y: float


@dataclass(frozen=True, slots=True)
class NavigationTraceEvent:
    """Describe one delivered Qt input event in replayable scalar form."""

    kind: str
    elapsed_ns: int
    local_x: float = 0.0
    local_y: float = 0.0
    global_x: float = 0.0
    global_y: float = 0.0
    button: int = 0
    buttons: int = 0
    modifiers: int = 0
    source: int = 0
    pixel_delta_x: int = 0
    pixel_delta_y: int = 0
    angle_delta_x: int = 0
    angle_delta_y: int = 0
    phase: int = 0
    inverted: bool = False
    key: int = 0
    auto_repeat: bool = False
    control_mode: str = ""


@dataclass(frozen=True, slots=True)
class NavigationTrace:
    """Own the complete immutable input trace and workload identity."""

    format_version: int
    logical_width: int
    logical_height: int
    device_pixel_ratio: float
    screen_refresh_hz: float
    control_mode: str
    navigation_settings: dict[str, bool | int | float]
    initial_state: NavigationState
    final_state: NavigationState
    document_path: str | None
    document_sha256: str | None
    events: tuple[NavigationTraceEvent, ...]


class NavigationTraceRecorder(QObject):
    """Record delivered mouse, wheel, and Space-key events from one canvas."""

    def __init__(
        self,
        canvas: NavigationTraceCanvas,
        output_path: Path,
        *,
        document_path: Path | None = None,
        status: Callable[[str], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        """Bind an inactive recorder to one canvas and destination."""
        super().__init__(parent)
        self._canvas = canvas
        self._output_path = output_path.resolve()
        self._document_path = None if document_path is None else document_path.resolve()
        self._status = status or (lambda _message: None)
        self._started_ns: int | None = None
        self._initial_state: NavigationState | None = None
        self._control_mode = ""
        self._events: list[NavigationTraceEvent] = []

    @property
    def active(self) -> bool:
        """Return whether input delivery is currently being recorded."""
        return self._started_ns is not None

    @property
    def output_path(self) -> Path:
        """Return the resolved trace destination."""
        return self._output_path

    def toggle(self) -> None:
        """Start or stop recording."""
        if self.active:
            self.stop()
        else:
            self.start()

    def start(self) -> None:
        """Start a fresh trace at the canvas's current navigation state."""
        if self.active:
            return
        if self._document_path is not None and not self._document_path.is_file():
            raise FileNotFoundError(self._document_path)
        self._events = []
        self._initial_state = self._navigation_state()
        self._control_mode = str(self._canvas.getControlMode())
        self._started_ns = time.perf_counter_ns()
        self._canvas.installEventFilter(self)
        self._connect_control_mode_signal()
        self._status(
            f"Navigation trace recording · press F9 to save {self._output_path.name}"
        )

    def stop(self) -> NavigationTrace | None:
        """Stop recording, persist the trace atomically, and return it."""
        if not self.active:
            return None
        self._disconnect_control_mode_signal()
        self._canvas.removeEventFilter(self)
        trace = NavigationTrace(
            format_version=TRACE_FORMAT_VERSION,
            logical_width=self._canvas.width(),
            logical_height=self._canvas.height(),
            device_pixel_ratio=float(self._canvas.devicePixelRatioF()),
            screen_refresh_hz=self._screen_refresh_hz(),
            control_mode=self._control_mode,
            navigation_settings=self._navigation_settings(),
            initial_state=self._initial_state or self._navigation_state(),
            final_state=self._navigation_state(),
            document_path=(
                None if self._document_path is None else str(self._document_path)
            ),
            document_sha256=(
                None
                if self._document_path is None
                else sha256_file(self._document_path)
            ),
            events=tuple(self._events),
        )
        self._started_ns = None
        self._initial_state = None
        self._control_mode = ""
        save_navigation_trace(self._output_path, trace)
        self._status(
            f"Saved {len(trace.events)} navigation events to {self._output_path}"
        )
        return trace

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Observe navigation-relevant events without changing delivery."""
        if watched is not self._canvas or self._started_ns is None:
            return False
        trace_event = self._trace_event(event)
        if trace_event is not None:
            self._events.append(trace_event)
        return False

    def _connect_control_mode_signal(self) -> None:
        """Record mode transitions consumed above the canvas event boundary."""
        signal = getattr(self._canvas, "controlModeChanged", None)
        connect = getattr(signal, "connect", None)
        if callable(connect):
            connect(self._record_control_mode)

    def _disconnect_control_mode_signal(self) -> None:
        """Release the optional control-mode signal connection."""
        signal = getattr(self._canvas, "controlModeChanged", None)
        disconnect = getattr(signal, "disconnect", None)
        if not callable(disconnect):
            return
        try:
            disconnect(self._record_control_mode)
        except RuntimeError:
            pass

    def _record_control_mode(self, mode: str) -> None:
        """Capture one effective-tool transition at its synchronous boundary."""
        if self._started_ns is None:
            return
        self._events.append(
            NavigationTraceEvent(
                kind="control_mode",
                elapsed_ns=time.perf_counter_ns() - self._started_ns,
                control_mode=str(mode),
            )
        )

    def _trace_event(self, event: QEvent) -> NavigationTraceEvent | None:
        """Convert one supported Qt event into detached scalar data."""
        elapsed_ns = time.perf_counter_ns() - (self._started_ns or 0)
        event_type = event.type()
        if event_type in {
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonRelease,
        } and isinstance(event, QMouseEvent):
            return self._mouse_event(event, event_type, elapsed_ns)
        if event_type is QEvent.Type.Wheel and isinstance(event, QWheelEvent):
            return self._wheel_event(event, elapsed_ns)
        if event_type in {QEvent.Type.KeyPress, QEvent.Type.KeyRelease} and isinstance(
            event,
            QKeyEvent,
        ):
            if event.key() != Qt.Key.Key_Space:
                return None
            return NavigationTraceEvent(
                kind=(
                    "key_press" if event_type is QEvent.Type.KeyPress else "key_release"
                ),
                elapsed_ns=elapsed_ns,
                modifiers=_enum_value(event.modifiers()),
                key=int(event.key()),
                auto_repeat=event.isAutoRepeat(),
            )
        return None

    @staticmethod
    def _mouse_event(
        event: QMouseEvent,
        event_type: QEvent.Type,
        elapsed_ns: int,
    ) -> NavigationTraceEvent:
        """Detach one mouse event."""
        local = event.position()
        global_position = event.globalPosition()
        kinds = {
            QEvent.Type.MouseButtonPress: "mouse_press",
            QEvent.Type.MouseMove: "mouse_move",
            QEvent.Type.MouseButtonRelease: "mouse_release",
        }
        return NavigationTraceEvent(
            kind=kinds[event_type],
            elapsed_ns=elapsed_ns,
            local_x=local.x(),
            local_y=local.y(),
            global_x=global_position.x(),
            global_y=global_position.y(),
            button=_enum_value(event.button()),
            buttons=_enum_value(event.buttons()),
            modifiers=_enum_value(event.modifiers()),
            source=_enum_value(event.source()),
        )

    @staticmethod
    def _wheel_event(
        event: QWheelEvent,
        elapsed_ns: int,
    ) -> NavigationTraceEvent:
        """Detach one wheel event."""
        local = event.position()
        global_position = event.globalPosition()
        pixel_delta = event.pixelDelta()
        angle_delta = event.angleDelta()
        return NavigationTraceEvent(
            kind="wheel",
            elapsed_ns=elapsed_ns,
            local_x=local.x(),
            local_y=local.y(),
            global_x=global_position.x(),
            global_y=global_position.y(),
            buttons=_enum_value(event.buttons()),
            modifiers=_enum_value(event.modifiers()),
            source=_enum_value(event.source()),
            pixel_delta_x=pixel_delta.x(),
            pixel_delta_y=pixel_delta.y(),
            angle_delta_x=angle_delta.x(),
            angle_delta_y=angle_delta.y(),
            phase=_enum_value(event.phase()),
            inverted=event.inverted(),
        )

    def _navigation_state(self) -> NavigationState:
        """Snapshot the canvas navigation values."""
        pan = self._canvas.getPan()
        return NavigationState(
            zoom=float(self._canvas.currentZoom()),
            pan_x=pan.x(),
            pan_y=pan.y(),
        )

    def _navigation_settings(self) -> dict[str, bool | int | float]:
        """Snapshot settings that change navigation event interpretation."""
        settings = getattr(self._canvas, "settings", None)
        captured: dict[str, bool | int | float] = {}
        for name in _NAVIGATION_SETTING_NAMES:
            value = getattr(settings, name, None)
            if isinstance(value, (bool, int, float)):
                captured[name] = value
        return captured

    def _screen_refresh_hz(self) -> float:
        """Return the current screen refresh rate when Qt exposes it."""
        screen_getter = getattr(self._canvas, "screen", None)
        screen = screen_getter() if callable(screen_getter) else None
        refresh_rate = getattr(screen, "refreshRate", None)
        if not callable(refresh_rate):
            return 0.0
        return max(0.0, float(refresh_rate()))


def save_navigation_trace(path: Path, trace: NavigationTrace) -> None:
    """Persist one trace atomically as stable, human-readable JSON."""
    destination = path.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    payload = asdict(trace)
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


def load_navigation_trace(path: Path) -> NavigationTrace:
    """Load and validate one navigation trace."""
    source = path.resolve()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise TypeError("navigation trace root must be an object")
    version = _required_int(payload, "format_version")
    if version != TRACE_FORMAT_VERSION:
        raise ValueError(
            f"unsupported navigation trace version: {version}; "
            f"expected {TRACE_FORMAT_VERSION}"
        )
    initial_state = _navigation_state(payload.get("initial_state"), "initial_state")
    final_state = _navigation_state(payload.get("final_state"), "final_state")
    raw_events = payload.get("events")
    if not isinstance(raw_events, list):
        raise TypeError("navigation trace events must be an array")
    events = tuple(
        _navigation_event(raw_event, index)
        for index, raw_event in enumerate(raw_events)
    )
    elapsed_values = [event.elapsed_ns for event in events]
    if elapsed_values != sorted(elapsed_values):
        raise ValueError("navigation trace event timestamps must be monotonic")
    trace = NavigationTrace(
        format_version=version,
        logical_width=_required_int(payload, "logical_width"),
        logical_height=_required_int(payload, "logical_height"),
        device_pixel_ratio=_required_float(payload, "device_pixel_ratio"),
        screen_refresh_hz=_required_float(payload, "screen_refresh_hz"),
        control_mode=_required_str(payload, "control_mode"),
        navigation_settings=_navigation_settings(payload.get("navigation_settings")),
        initial_state=initial_state,
        final_state=final_state,
        document_path=_optional_str(payload, "document_path"),
        document_sha256=_optional_str(payload, "document_sha256"),
        events=events,
    )
    if trace.logical_width <= 0 or trace.logical_height <= 0:
        raise ValueError("navigation trace viewport dimensions must be positive")
    if trace.device_pixel_ratio <= 0.0:
        raise ValueError("navigation trace DPR must be positive")
    if not trace.events:
        raise ValueError("navigation trace must contain at least one event")
    return trace


def sha256_file(path: Path) -> str:
    """Return the lowercase SHA-256 digest of one file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _navigation_state(value: object, field_name: str) -> NavigationState:
    """Validate one serialized navigation state."""
    if not isinstance(value, Mapping):
        raise TypeError(f"navigation trace {field_name} must be an object")
    return NavigationState(
        zoom=_required_float(value, "zoom"),
        pan_x=_required_float(value, "pan_x"),
        pan_y=_required_float(value, "pan_y"),
    )


def _navigation_event(value: object, index: int) -> NavigationTraceEvent:
    """Validate one serialized navigation event."""
    if not isinstance(value, Mapping):
        raise TypeError(f"navigation trace event {index} must be an object")
    supported = {
        "mouse_press",
        "mouse_move",
        "mouse_release",
        "wheel",
        "key_press",
        "key_release",
        "control_mode",
    }
    kind = _required_str(value, "kind")
    if kind not in supported:
        raise ValueError(f"unsupported navigation trace event kind: {kind!r}")
    fields = NavigationTraceEvent.__dataclass_fields__
    unknown = set(value) - set(fields)
    if unknown:
        raise ValueError(
            f"navigation trace event {index} has unknown fields: {sorted(unknown)}"
        )
    defaults = NavigationTraceEvent(kind=kind, elapsed_ns=0)
    values: dict[str, Any] = {}
    for name in fields:
        raw = value.get(name, getattr(defaults, name))
        expected = fields[name].type
        if expected == "bool":
            if not isinstance(raw, bool):
                raise ValueError(f"navigation trace event {index}.{name} must be bool")
        elif expected == "float":
            if not isinstance(raw, (int, float)) or isinstance(raw, bool):
                raise ValueError(
                    f"navigation trace event {index}.{name} must be numeric"
                )
            raw = float(raw)
        elif expected == "int":
            if not isinstance(raw, int) or isinstance(raw, bool):
                raise ValueError(f"navigation trace event {index}.{name} must be int")
        elif expected == "str" and not isinstance(raw, str):
            raise TypeError(f"navigation trace event {index}.{name} must be str")
        values[name] = raw
    event = NavigationTraceEvent(**values)
    if event.elapsed_ns < 0:
        raise ValueError(
            f"navigation trace event {index} timestamp must be nonnegative"
        )
    return event


def _navigation_settings(value: object) -> dict[str, bool | int | float]:
    """Validate serialized settings that affect navigation behavior."""
    if not isinstance(value, Mapping):
        raise TypeError("navigation trace navigation_settings must be an object")
    unknown = set(value) - set(_NAVIGATION_SETTING_NAMES)
    if unknown:
        raise ValueError(f"unknown navigation trace settings: {sorted(unknown)}")
    settings: dict[str, bool | int | float] = {}
    for name, raw in value.items():
        if not isinstance(raw, (bool, int, float)):
            raise TypeError(f"navigation trace setting {name} must be scalar")
        settings[str(name)] = raw
    return settings


def _required_int(payload: Mapping[str, object], name: str) -> int:
    """Return one required integer field."""
    value = payload.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"navigation trace {name} must be an integer")
    return value


def _required_float(payload: Mapping[str, object], name: str) -> float:
    """Return one required numeric field as float."""
    value = payload.get(name)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"navigation trace {name} must be numeric")
    return float(value)


def _required_str(payload: Mapping[str, object], name: str) -> str:
    """Return one required string field."""
    value = payload.get(name)
    if not isinstance(value, str):
        raise TypeError(f"navigation trace {name} must be a string")
    return value


def _optional_str(payload: Mapping[str, object], name: str) -> str | None:
    """Return one optional string field."""
    value = payload.get(name)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"navigation trace {name} must be a string or null")
    return value


def _enum_value(value: object) -> int:
    """Return the integer payload of one Qt enum or flag."""
    return int(getattr(value, "value", value))


__all__ = [
    "NavigationState",
    "NavigationTrace",
    "NavigationTraceEvent",
    "NavigationTraceRecorder",
    "load_navigation_trace",
    "save_navigation_trace",
    "sha256_file",
]
