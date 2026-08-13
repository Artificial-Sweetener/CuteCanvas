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

"""Tests for real-input navigation trace capture and reconstruction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, Signal
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QWidget

from cutecanvas_test_support.harness_tools.cutecanvas_navigation_trace_harness import (
    _checkpoint_difference_is_acceptable,
    _pan_checkpoint_event_indices,
    qt_event_from_trace,
)
from demonstration.navigation_trace import (
    NavigationTraceEvent,
    NavigationTraceRecorder,
    load_navigation_trace,
)


class _TraceWidget(QWidget):
    """Expose stable navigation values to the generic recorder."""

    controlModeChanged = Signal(str)

    def __init__(self) -> None:
        """Create one small trace target."""
        super().__init__()
        self._pan = QPointF(12.5, -7.25)
        self._zoom = 5.0

    def getControlMode(self) -> str:
        """Return the test control mode."""
        return "panzoom"

    def getPan(self) -> QPointF:
        """Return the test pan."""
        return QPointF(self._pan)

    def currentZoom(self) -> float:
        """Return the test zoom."""
        return self._zoom

    def set_control_mode(self, mode: str) -> None:
        """Emit one effective control-mode transition."""
        self.controlModeChanged.emit(mode)


def test_navigation_recorder_captures_delivered_mouse_and_wheel_events(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    """The recorder should persist delivered event geometry and terminal state."""
    widget = _TraceWidget()
    widget.resize(640, 480)
    widget.show()
    qapp.processEvents()
    output = tmp_path / "navigation.json"
    recorder = NavigationTraceRecorder(widget, output)
    recorder.start()

    mouse = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(120.5, 80.25),
        QPointF(120.5, 80.25),
        QPointF(420.5, 280.25),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        Qt.MouseEventSource.MouseEventNotSynthesized,
    )
    wheel = QWheelEvent(
        QPointF(120.5, 80.25),
        QPointF(420.5, 280.25),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ControlModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
        Qt.MouseEventSource.MouseEventNotSynthesized,
    )
    QApplication.sendEvent(widget, mouse)
    widget.set_control_mode("cursor")
    QApplication.sendEvent(widget, wheel)
    widget._pan = QPointF(30.0, 40.0)
    widget._zoom = 6.25

    trace = recorder.stop()
    loaded = load_navigation_trace(output)

    assert trace is not None
    assert loaded.logical_width == 640
    assert loaded.logical_height == 480
    assert loaded.control_mode == "panzoom"
    assert loaded.initial_state.zoom == 5.0
    assert loaded.final_state.zoom == 6.25
    assert loaded.final_state.pan_x == 30.0
    assert [event.kind for event in loaded.events] == [
        "mouse_move",
        "control_mode",
        "wheel",
    ]
    assert loaded.events[0].local_x == 120.5
    assert loaded.events[0].buttons == int(Qt.MouseButton.LeftButton.value)
    assert loaded.events[1].control_mode == "cursor"
    assert loaded.events[2].angle_delta_y == 120
    assert loaded.events[0].elapsed_ns <= loaded.events[2].elapsed_ns
    widget.close()


def test_navigation_trace_loader_rejects_nonmonotonic_event_time(
    tmp_path: Path,
) -> None:
    """Replay should reject traces whose delivery chronology is impossible."""
    path = tmp_path / "invalid.json"
    payload = {
        "format_version": 1,
        "logical_width": 640,
        "logical_height": 480,
        "device_pixel_ratio": 1.0,
        "screen_refresh_hz": 60.0,
        "control_mode": "panzoom",
        "navigation_settings": {},
        "initial_state": {"zoom": 5.0, "pan_x": 0.0, "pan_y": 0.0},
        "final_state": {"zoom": 5.0, "pan_x": 0.0, "pan_y": 0.0},
        "document_path": None,
        "document_sha256": None,
        "events": [
            {"kind": "mouse_move", "elapsed_ns": 20},
            {"kind": "mouse_move", "elapsed_ns": 10},
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="monotonic"):
        load_navigation_trace(path)


def test_trace_event_reconstruction_preserves_wheel_payload() -> None:
    """Headless replay should reconstruct the recorded wheel delta and phase."""
    trace_event = NavigationTraceEvent(
        kind="wheel",
        elapsed_ns=100,
        local_x=15.5,
        local_y=25.25,
        global_x=115.5,
        global_y=225.25,
        modifiers=int(Qt.KeyboardModifier.AltModifier.value),
        angle_delta_y=-120,
        phase=int(Qt.ScrollPhase.ScrollUpdate.value),
        source=int(Qt.MouseEventSource.MouseEventNotSynthesized.value),
    )

    event = qt_event_from_trace(trace_event, scale_x=2.0, scale_y=3.0)

    assert isinstance(event, QWheelEvent)
    assert event.position() == QPointF(31.0, 75.75)
    assert event.angleDelta() == QPoint(0, -120)
    assert event.phase() is Qt.ScrollPhase.ScrollUpdate
    assert event.modifiers() == Qt.KeyboardModifier.AltModifier


def test_trace_correctness_checkpoints_cover_active_and_settled_pan_frames() -> None:
    """Correctness replay should cover retained moves and the settling release."""
    left_button = int(Qt.MouseButton.LeftButton.value)
    checkpoints = _pan_checkpoint_event_indices(
        (
            NavigationTraceEvent(
                kind="mouse_press",
                elapsed_ns=0,
                button=left_button,
            ),
            NavigationTraceEvent(
                kind="mouse_move",
                elapsed_ns=1,
                buttons=left_button,
            ),
            NavigationTraceEvent(
                kind="mouse_release",
                elapsed_ns=2,
                button=left_button,
            ),
            NavigationTraceEvent(
                kind="wheel",
                elapsed_ns=3,
                angle_delta_y=120,
            ),
            NavigationTraceEvent(
                kind="mouse_press",
                elapsed_ns=4,
                button=left_button,
            ),
            NavigationTraceEvent(
                kind="mouse_release",
                elapsed_ns=5,
                button=left_button,
            ),
        ),
        4,
    )

    assert checkpoints == {1, 2}


def test_active_checkpoint_budget_rejects_bands_but_allows_sparse_sampling() -> None:
    """Active replay should tolerate sparse filtering drift, not displaced bands."""

    def difference(mismatch_pixels: int) -> dict[str, object]:
        """Return the comparison fields consumed by the checkpoint policy."""
        return {"mismatch_pixels": mismatch_pixels}

    assert _checkpoint_difference_is_acceptable(
        difference(11_000),
        difference(339),
        settled=False,
        physical_pixels=25_401_600,
    )
    assert _checkpoint_difference_is_acceptable(
        difference(11_000),
        difference(1_061),
        settled=False,
        physical_pixels=25_401_600,
    )
    assert not _checkpoint_difference_is_acceptable(
        difference(11_000),
        difference(2_541),
        settled=False,
        physical_pixels=25_401_600,
    )
    assert not _checkpoint_difference_is_acceptable(
        difference(25_403),
        difference(0),
        settled=False,
        physical_pixels=25_401_600,
    )
    assert not _checkpoint_difference_is_acceptable(
        difference(1),
        difference(0),
        settled=True,
        physical_pixels=25_401_600,
    )
