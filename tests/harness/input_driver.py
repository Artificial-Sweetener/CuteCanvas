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

"""Drive real Qt mouse, touch, and tablet paths against a mounted QPane."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt
from PySide6.QtGui import QInputDevice, QMouseEvent, QPointingDevice, QTabletEvent
from PySide6.QtTest import QTest

from .abuse_model import (
    MouseHoverAction,
    PalmContactAction,
    PenHoverAction,
    PointerKind,
    StrokeAction,
    TouchNavigationAction,
)
from .mounted_qpane import MountedQPaneHarness


class QtStrokeDriver:
    """Translate device-neutral stroke actions into genuine Qt event streams."""

    def __init__(self, harness: MountedQPaneHarness) -> None:
        """Create reusable synthetic touch and tablet devices."""
        self._harness = harness
        self._touch_device = QTest.createTouchDevice()
        self._pen_device = QPointingDevice(
            "QPane abuse pen",
            8801,
            QInputDevice.DeviceType.Stylus,
            QPointingDevice.PointerType.Pen,
            QInputDevice.Capability.Position
            | QInputDevice.Capability.Pressure
            | QInputDevice.Capability.Hover,
            1,
            1,
        )

    def begin(self, action: StrokeAction) -> None:
        """Send the first contact event for ``action``."""
        point = action.points[0].to_qpoint()
        if action.device is PointerKind.MOUSE:
            QTest.mousePress(
                self._harness.viewer,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                point,
            )
        elif action.device is PointerKind.TOUCH:
            QTest.touchEvent(
                self._harness.viewer,
                self._touch_device,
            ).press(0, point, self._harness.viewer).commit()
        else:
            self._send_tablet(
                QEvent.Type.TabletPress,
                point,
                pressure=action.pressure,
                buttons=Qt.MouseButton.LeftButton,
            )
        self._advance(action.step_delay_ms)

    def move(self, action: StrokeAction, point_index: int) -> None:
        """Send one continued-contact sample from ``action``."""
        point = action.points[point_index].to_qpoint()
        if action.device is PointerKind.MOUSE:
            QTest.mouseMove(self._harness.viewer, point, delay=action.step_delay_ms)
        elif action.device is PointerKind.TOUCH:
            QTest.touchEvent(
                self._harness.viewer,
                self._touch_device,
            ).move(0, point, self._harness.viewer).commit()
            self._advance(action.step_delay_ms)
        else:
            self._send_tablet(
                QEvent.Type.TabletMove,
                point,
                pressure=action.pressure,
                buttons=Qt.MouseButton.LeftButton,
            )
            self._advance(action.step_delay_ms)

    def end(self, action: StrokeAction, *, drain: bool = True) -> None:
        """Release the active pointer, optionally preserving queued transition work."""
        point = action.points[-1].to_qpoint()
        if action.device is PointerKind.MOUSE:
            QTest.mouseRelease(
                self._harness.viewer,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                point,
            )
        elif action.device is PointerKind.TOUCH:
            QTest.touchEvent(
                self._harness.viewer,
                self._touch_device,
            ).release(0, point, self._harness.viewer).commit()
        else:
            self._send_tablet(
                QEvent.Type.TabletRelease,
                point,
                pressure=0.0,
                buttons=Qt.MouseButton.NoButton,
            )
        if drain:
            self._advance(action.step_delay_ms)

    def leave_pen_proximity(self) -> None:
        """Send the application-level proximity transition emitted by hardware."""
        self._send_tablet(
            QEvent.Type.TabletLeaveProximity,
            QPoint(),
            pressure=0.0,
            buttons=Qt.MouseButton.NoButton,
            receiver=self._harness.qapp,
        )
        self._harness.drain_events()

    def begin_touch_navigation(self, action: TouchNavigationAction) -> None:
        """Begin the provisional one-finger phase of touch navigation."""
        primary = action.primary_start.to_qpoint()
        QTest.touchEvent(self._harness.viewer, self._touch_device).press(
            0, primary, self._harness.viewer
        ).commit()
        self._harness.drain_events()

    def add_secondary_touch(self, action: TouchNavigationAction) -> None:
        """Add the contact that transfers ownership from painting to navigation."""
        primary = action.primary_start.to_qpoint()
        secondary = action.secondary_start.to_qpoint()
        QTest.touchEvent(self._harness.viewer, self._touch_device).move(
            0, primary, self._harness.viewer
        ).press(1, secondary, self._harness.viewer).commit()
        self._harness.drain_events()

    def move_touch_navigation(self, action: TouchNavigationAction) -> None:
        """Move both active contacts through the normal Qt touch frame path."""
        QTest.touchEvent(self._harness.viewer, self._touch_device).move(
            0, action.primary_end.to_qpoint(), self._harness.viewer
        ).move(1, action.secondary_end.to_qpoint(), self._harness.viewer).commit()
        self._harness.drain_events()

    def end_touch_navigation(self, action: TouchNavigationAction) -> None:
        """Release both navigation contacts in one Qt touch frame."""
        QTest.touchEvent(self._harness.viewer, self._touch_device).release(
            0, action.primary_end.to_qpoint(), self._harness.viewer
        ).release(1, action.secondary_end.to_qpoint(), self._harness.viewer).commit()
        self._harness.drain_events()

    def send_palm_contact(self, action: PalmContactAction) -> None:
        """Send a complete touch contact while the pen owns proximity."""
        point = action.point.to_qpoint()
        QTest.touchEvent(self._harness.viewer, self._touch_device).press(
            0, point, self._harness.viewer
        ).commit()
        QTest.touchEvent(self._harness.viewer, self._touch_device).release(
            0, point, self._harness.viewer
        ).commit()
        self._harness.drain_events()

    def hover_pen(self, action: PenHoverAction) -> None:
        """Move the hover-capable synthetic stylus without contact."""
        self._send_tablet(
            QEvent.Type.TabletMove,
            action.point.to_qpoint(),
            pressure=0.0,
            buttons=Qt.MouseButton.NoButton,
        )
        self._harness.drain_events()

    def hover_mouse(self, action: MouseHoverAction) -> None:
        """Send mouse motion through the mounted host window's hit-test path."""
        window = self._harness.host.windowHandle()
        if window is None:
            raise RuntimeError("Mounted QPane host has no window handle")
        viewer_point = action.point.to_qpoint()
        host_point = self._harness.viewer.mapTo(self._harness.host, viewer_point)
        if not action.stale_touchscreen_metadata:
            QTest.mouseMove(window, host_point)
            self._harness.drain_events()
            return
        position = QPointF(host_point)
        global_position = QPointF(self._harness.host.mapToGlobal(host_point))
        event = QMouseEvent(
            QEvent.Type.MouseMove,
            position,
            position,
            global_position,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.MouseEventSource.MouseEventSynthesizedBySystem,
            self._touch_device,
        )
        self._harness.qapp.sendEvent(window, event)
        self._harness.drain_events()

    def _send_tablet(
        self,
        event_type: QEvent.Type,
        point: QPoint,
        *,
        pressure: float,
        buttons: Qt.MouseButton,
        receiver: QObject | None = None,
    ) -> None:
        """Send one pressure-bearing tablet event to the mounted pane."""
        position = QPointF(point)
        event = QTabletEvent(
            event_type,
            self._pen_device,
            position,
            position,
            pressure,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            Qt.KeyboardModifier.NoModifier,
            Qt.MouseButton.LeftButton if buttons else Qt.MouseButton.NoButton,
            buttons,
        )
        self._harness.qapp.sendEvent(receiver or self._harness.viewer, event)

    def _advance(self, delay_ms: int) -> None:
        """Advance Qt timers without replacing the normal event path."""
        if delay_ms > 0:
            QTest.qWait(delay_ms)
        self._harness.drain_events()
