#    QPane - High-performance PySide6 image viewer
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

"""Wheel zoom magnitude, snapping, and navigation-lifecycle contracts."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qpane import NavigationInteractionPort, PanZoomTool
from qpane.rendering import ViewportZoomMode


class _WheelEventStub:
    """Provide deterministic wheel values without native event delivery."""

    def __init__(
        self,
        point: QPointF,
        delta_y: int,
        phase: Qt.ScrollPhase = Qt.ScrollPhase.NoScrollPhase,
    ) -> None:
        """Capture wheel position, delta, and lifecycle phase."""
        self._point = QPointF(point)
        self._delta_y = delta_y
        self._phase = phase
        self.accepted = False

    def position(self) -> QPointF:
        """Return the stable logical zoom anchor."""
        return QPointF(self._point)

    def angleDelta(self) -> QPoint:
        """Return the configured vertical wheel delta."""
        return QPoint(0, self._delta_y)

    def phase(self) -> Qt.ScrollPhase:
        """Return the configured gesture lifecycle phase."""
        return self._phase

    def accept(self) -> None:
        """Record that the tool consumed this event."""
        self.accepted = True


def test_panzoom_wheel_respects_navigation_lock(qapp: QApplication) -> None:
    """Locked navigation must ignore wheel input."""
    del qapp
    tool = PanZoomTool()
    received: list[float] = []
    tool.signals.zoom_requested.connect(lambda zoom, _anchor: received.append(zoom))
    tool.activate(
        NavigationInteractionPort(
            is_navigation_locked=lambda: True,
            is_content_empty=lambda: False,
            get_zoom=lambda: 1.0,
        )
    )

    tool.wheelEvent(_WheelEventStub(QPointF(10, 10), 120))

    assert received == []


def test_panzoom_wheel_emits_zoom(qapp: QApplication) -> None:
    """Wheel direction must apply the historical zoom factors."""
    del qapp
    tool = PanZoomTool()
    zooms: list[tuple[float, QPointF]] = []
    current_zoom = 2.0

    def on_zoom(value: float, anchor: QPointF) -> None:
        """Record and adopt the requested zoom."""
        nonlocal current_zoom
        zooms.append((value, anchor))
        current_zoom = value

    tool.signals.zoom_requested.connect(on_zoom)
    tool.activate(
        NavigationInteractionPort(
            is_navigation_locked=lambda: False,
            is_content_empty=lambda: False,
            get_zoom=lambda: current_zoom,
            get_native_zoom=lambda _point: 1.0,
        )
    )

    tool.wheelEvent(_WheelEventStub(QPointF(5, 5), 120))
    tool.wheelEvent(_WheelEventStub(QPointF(5, 5), -120))

    assert zooms[0][0] == pytest.approx(2.5)
    assert zooms[0][1] == QPointF(5, 5)
    assert zooms[1][0] == pytest.approx(2.0)


def test_scroll_phases_bound_one_wheel_navigation_session(
    qapp: QApplication,
) -> None:
    """Keep refinement suspended across every update in one wheel gesture."""
    del qapp
    tool = PanZoomTool()
    lifecycle: list[str] = []
    current_zoom = 2.0

    def on_zoom(value: float, _anchor: QPointF) -> None:
        """Adopt each requested zoom through the host port."""
        nonlocal current_zoom
        current_zoom = value

    tool.signals.navigation_started.connect(lambda: lifecycle.append("started"))
    tool.signals.navigation_finished.connect(lambda: lifecycle.append("finished"))
    tool.signals.zoom_requested.connect(on_zoom)
    tool.activate(
        NavigationInteractionPort(
            is_navigation_locked=lambda: False,
            is_content_empty=lambda: False,
            get_zoom=lambda: current_zoom,
            get_native_zoom=lambda _point: 1.0,
        )
    )

    tool.wheelEvent(_WheelEventStub(QPointF(5, 5), 120, Qt.ScrollPhase.ScrollBegin))
    tool.wheelEvent(_WheelEventStub(QPointF(5, 5), 120, Qt.ScrollPhase.ScrollUpdate))
    assert lifecycle == ["started"]

    end = _WheelEventStub(QPointF(5, 5), 0, Qt.ScrollPhase.ScrollEnd)
    tool.wheelEvent(end)

    assert lifecycle == ["started", "finished"]
    assert end.accepted is True


def test_explicit_wheel_session_waits_for_scroll_end(qapp: QApplication) -> None:
    """Do not end a phased gesture merely because one update is expensive."""
    tool = PanZoomTool()
    lifecycle: list[str] = []
    tool.signals.navigation_started.connect(lambda: lifecycle.append("started"))
    tool.signals.navigation_finished.connect(lambda: lifecycle.append("finished"))
    tool.activate(
        NavigationInteractionPort(
            is_navigation_locked=lambda: False,
            is_content_empty=lambda: False,
            get_zoom=lambda: 2.0,
            get_native_zoom=lambda _point: 1.0,
        )
    )

    tool.wheelEvent(_WheelEventStub(QPointF(5, 5), 120, Qt.ScrollPhase.ScrollBegin))
    QTest.qWait(tool._WHEEL_SESSION_IDLE_MS + 40)
    qapp.processEvents()

    assert lifecycle == ["started"]

    tool.wheelEvent(_WheelEventStub(QPointF(5, 5), 0, Qt.ScrollPhase.ScrollEnd))

    assert lifecycle == ["started", "finished"]


def test_wheel_navigation_session_ends_after_idle(qapp: QApplication) -> None:
    """Close an unphased wheel burst when its platform sends no explicit end."""
    tool = PanZoomTool()
    lifecycle: list[str] = []
    tool.signals.navigation_started.connect(lambda: lifecycle.append("started"))
    tool.signals.navigation_finished.connect(lambda: lifecycle.append("finished"))
    tool.activate(
        NavigationInteractionPort(
            is_navigation_locked=lambda: False,
            is_content_empty=lambda: False,
            get_zoom=lambda: 2.0,
            get_native_zoom=lambda _point: 1.0,
        )
    )

    tool.wheelEvent(_WheelEventStub(QPointF(5, 5), 120))
    assert lifecycle == ["started"]

    QTest.qWait(tool._WHEEL_SESSION_IDLE_MS + 40)
    qapp.processEvents()

    assert lifecycle == ["started", "finished"]


def test_panzoom_wheel_uses_delta_magnitude(qapp: QApplication) -> None:
    """Multi-step deltas must compound the per-step zoom factor."""
    del qapp
    tool = PanZoomTool()
    zooms: list[float] = []
    current_zoom = 2.0

    def on_zoom(value: float, _anchor: QPointF) -> None:
        """Record and adopt the requested zoom."""
        nonlocal current_zoom
        zooms.append(value)
        current_zoom = value

    tool.signals.zoom_requested.connect(on_zoom)
    tool.activate(
        NavigationInteractionPort(
            is_navigation_locked=lambda: False,
            is_content_empty=lambda: False,
            get_zoom=lambda: current_zoom,
            get_native_zoom=lambda _point: 1.0,
        )
    )
    grow_event = _WheelEventStub(QPointF(5, 5), 240)
    tool.wheelEvent(grow_event)
    shrink_event = _WheelEventStub(QPointF(5, 5), -240)
    tool.wheelEvent(shrink_event)

    assert zooms[0] == pytest.approx(2.0 * 1.25 * 1.25)
    assert zooms[1] == pytest.approx(2.0)
    assert grow_event.accepted is True
    assert shrink_event.accepted is True


@pytest.mark.parametrize(
    ("current_zoom", "native_zoom", "delta"),
    ((0.9, 1.0, 120), (1.2, 1.0, -120), (1.4, 1.5, 120)),
)
def test_panzoom_wheel_snaps_when_crossing_native_zoom(
    qapp: QApplication,
    current_zoom: float,
    native_zoom: float,
    delta: int,
) -> None:
    """Crossing native scale in either direction must snap to one-to-one."""
    del qapp
    tool = PanZoomTool()
    emissions: list[tuple[float, ViewportZoomMode]] = []
    adopted_zoom = current_zoom

    def on_snap(value: float, _anchor: QPointF, mode: ViewportZoomMode) -> None:
        """Record and adopt the requested semantic zoom."""
        nonlocal adopted_zoom
        emissions.append((value, mode))
        adopted_zoom = value

    tool.signals.zoom_snap_requested.connect(on_snap)
    tool.activate(
        NavigationInteractionPort(
            is_navigation_locked=lambda: False,
            is_content_empty=lambda: False,
            get_zoom=lambda: adopted_zoom,
            get_native_zoom=lambda _point: native_zoom,
        )
    )

    tool.wheelEvent(_WheelEventStub(QPointF(5, 5), delta))

    assert emissions == [(native_zoom, ViewportZoomMode.ONE_TO_ONE)]
