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

"""Tests for pan/zoom tool snap-to-fit behavior."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF
from qpane import NavigationInteractionPort, PanZoomTool
from qpane.rendering import ViewportZoomMode


class _WheelEventStub:
    def __init__(self, point: QPointF, delta_y: int):
        self._point = QPointF(point)
        self._delta_y = delta_y

    def position(self) -> QPointF:
        return QPointF(self._point)

    def angleDelta(self) -> QPoint:
        return QPoint(0, self._delta_y)


def test_panzoom_wheel_snaps_to_fit_zoom(qapp):
    tool = PanZoomTool()
    emissions: list[tuple[float, ViewportZoomMode]] = []
    current_zoom = 0.4
    native_zoom = 1.0
    fit_zoom = 0.5  # Target fit zoom

    def on_snap(value: float, _anchor: QPoint, mode: ViewportZoomMode) -> None:
        nonlocal current_zoom
        emissions.append((value, mode))
        current_zoom = value

    tool.signals.zoom_snap_requested.connect(on_snap)
    tool.activate(
        NavigationInteractionPort(
            is_navigation_locked=lambda: False,
            is_content_empty=lambda: False,
            get_pan=lambda: QPointF(0, 0),
            get_zoom=lambda: current_zoom,
            get_native_zoom=lambda _point: native_zoom,
            get_fit_zoom=lambda: fit_zoom,
        )
    )

    # Zoom in from 0.4 -> should cross 0.5 (fit) -> snap to 0.5
    # 0.4 * 1.25 = 0.5 exactly, but let's assume it crosses or hits it.
    tool.wheelEvent(_WheelEventStub(QPointF(5, 5), 120))
    assert emissions == [(fit_zoom, ViewportZoomMode.FIT)]


def test_panzoom_wheel_snaps_to_fit_zoom_crossing(qapp):
    tool = PanZoomTool()
    emissions: list[tuple[float, ViewportZoomMode]] = []
    current_zoom = 0.45
    native_zoom = 1.0
    fit_zoom = 0.5

    def on_snap(value: float, _anchor: QPoint, mode: ViewportZoomMode) -> None:
        nonlocal current_zoom
        emissions.append((value, mode))
        current_zoom = value

    tool.signals.zoom_snap_requested.connect(on_snap)
    tool.activate(
        NavigationInteractionPort(
            is_navigation_locked=lambda: False,
            is_content_empty=lambda: False,
            get_pan=lambda: QPointF(0, 0),
            get_zoom=lambda: current_zoom,
            get_native_zoom=lambda _point: native_zoom,
            get_fit_zoom=lambda: fit_zoom,
        )
    )

    # Zoom in from 0.45 * 1.25 = 0.5625 -> crosses 0.5 -> snap to 0.5
    tool.wheelEvent(_WheelEventStub(QPointF(5, 5), 120))
    assert emissions == [(fit_zoom, ViewportZoomMode.FIT)]


def test_panzoom_wheel_snaps_to_fit_zoom_reverse(qapp):
    tool = PanZoomTool()
    emissions: list[tuple[float, ViewportZoomMode]] = []
    current_zoom = 0.6
    native_zoom = 1.0
    fit_zoom = 0.5

    def on_snap(value: float, _anchor: QPoint, mode: ViewportZoomMode) -> None:
        nonlocal current_zoom
        emissions.append((value, mode))
        current_zoom = value

    tool.signals.zoom_snap_requested.connect(on_snap)
    tool.activate(
        NavigationInteractionPort(
            is_navigation_locked=lambda: False,
            is_content_empty=lambda: False,
            get_pan=lambda: QPointF(0, 0),
            get_zoom=lambda: current_zoom,
            get_native_zoom=lambda _point: native_zoom,
            get_fit_zoom=lambda: fit_zoom,
        )
    )

    # Zoom out from 0.6 * 0.8 = 0.48 -> crosses 0.5 -> snap to 0.5
    tool.wheelEvent(_WheelEventStub(QPointF(5, 5), -120))
    assert emissions == [(fit_zoom, ViewportZoomMode.FIT)]


def test_panzoom_prioritizes_native_over_fit_if_both_crossed(qapp):
    tool = PanZoomTool()
    emissions: list[tuple[float, ViewportZoomMode]] = []
    current_zoom = 0.9
    native_zoom = 1.0
    fit_zoom = 1.05  # Very close to native

    def on_snap(value: float, _anchor: QPoint, mode: ViewportZoomMode) -> None:
        nonlocal current_zoom
        emissions.append((value, mode))
        current_zoom = value

    tool.signals.zoom_snap_requested.connect(on_snap)
    tool.activate(
        NavigationInteractionPort(
            is_navigation_locked=lambda: False,
            is_content_empty=lambda: False,
            get_pan=lambda: QPointF(0, 0),
            get_zoom=lambda: current_zoom,
            get_native_zoom=lambda _point: native_zoom,
            get_fit_zoom=lambda: fit_zoom,
        )
    )

    # Zoom in from 0.9 * 1.25 = 1.125 -> crosses both 1.0 and 1.05
    # Should prioritize native (1.0)
    tool.wheelEvent(_WheelEventStub(QPointF(5, 5), 120))
    assert emissions == [(native_zoom, ViewportZoomMode.ONE_TO_ONE)]
