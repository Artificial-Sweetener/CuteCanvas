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

"""Interactively simulate touch, active-pen, eraser, and mouse transitions."""

from __future__ import annotations

import sys

from cutecanvas import CuteCanvas
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import (
    QColor,
    QImage,
    QInputDevice,
    QMouseEvent,
    QPainter,
    QPen,
    QPointingDevice,
    QTabletEvent,
)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from examples.demonstration.touch_and_pen import build_touch_mask_editor


class PointerSimulator:
    """Own synthetic pointer devices and their active contact lifecycles."""

    def __init__(
        self,
        viewer: CuteCanvas,
        *,
        device_selector: QComboBox,
        x_slider: QSlider,
        y_slider: QSlider,
        pressure_slider: QSlider,
        status: QLabel,
    ) -> None:
        """Capture controls and create reusable synthetic Qt devices."""
        self._viewer = viewer
        self._device_selector = device_selector
        self._x_slider = x_slider
        self._y_slider = y_slider
        self._pressure_slider = pressure_slider
        self._status = status
        capabilities = (
            QInputDevice.Capability.Position
            | QInputDevice.Capability.Pressure
            | QInputDevice.Capability.Hover
        )
        self._pen = QPointingDevice(
            "Simulated active pen",
            9001,
            QInputDevice.DeviceType.Stylus,
            QPointingDevice.PointerType.Pen,
            capabilities,
            1,
            1,
        )
        self._eraser = QPointingDevice(
            "Simulated eraser",
            9002,
            QInputDevice.DeviceType.Stylus,
            QPointingDevice.PointerType.Eraser,
            capabilities,
            1,
            1,
        )
        self._touch = QTest.createTouchDevice()
        self._touch_active = False

    def hover(self) -> None:
        """Move the selected pen end while floating above the drawing surface."""
        self._send_tablet(
            QEvent.Type.TabletMove,
            pressure=0.0,
            buttons=Qt.MouseButton.NoButton,
        )
        self._status.setText("Hover: preview only; the mask is unchanged.")

    def pen_down(self) -> None:
        """Begin one pressure-sensitive pen or eraser stroke."""
        self._send_tablet(
            QEvent.Type.TabletPress,
            pressure=self._pressure(),
            buttons=Qt.MouseButton.LeftButton,
        )
        self._status.setText("Pen contact: pressure controls the live diameter.")

    def pen_move(self) -> None:
        """Move an active pen stroke to the selected coordinates."""
        self._send_tablet(
            QEvent.Type.TabletMove,
            pressure=self._pressure(),
            buttons=Qt.MouseButton.LeftButton,
        )
        self._status.setText("Pen move: position and pressure were updated.")

    def pen_up(self) -> None:
        """Release the pen while keeping its nominal hover preview visible."""
        self._send_tablet(
            QEvent.Type.TabletRelease,
            pressure=0.0,
            buttons=Qt.MouseButton.NoButton,
        )
        self._status.setText("Pen release: the configured hover-size preview returns.")

    def leave_proximity(self) -> None:
        """Simulate moving the active pen beyond the digitizer's hover range."""
        application = QApplication.instance()
        if application is None:
            return
        event = self._tablet_event(
            QEvent.Type.TabletLeaveProximity,
            pressure=0.0,
            buttons=Qt.MouseButton.NoButton,
        )
        QApplication.sendEvent(application, event)
        self._status.setText("Pen left proximity: floating feedback was removed.")

    def touch_down(self) -> None:
        """Begin a direct one-finger touch painting sequence."""
        if self._touch_active:
            return
        QTest.touchEvent(self._viewer, self._touch).press(
            0,
            self._position().toPoint(),
            self._viewer,
        ).commit()
        self._touch_active = True
        self._process_events()
        self._status.setText("Touch contact: fixed-size brush feedback is visible.")

    def touch_move(self) -> None:
        """Move the active one-finger touch painting sequence."""
        if not self._touch_active:
            self.touch_down()
            return
        QTest.touchEvent(self._viewer, self._touch).move(
            0,
            self._position().toPoint(),
            self._viewer,
        ).commit()
        self._process_events()
        self._status.setText("Touch move: the fixed-size brush followed the contact.")

    def touch_up(self) -> None:
        """Finish the active touch sequence and remove its preview."""
        if not self._touch_active:
            return
        QTest.touchEvent(self._viewer, self._touch).release(
            0,
            self._position().toPoint(),
            self._viewer,
        ).commit()
        self._touch_active = False
        self._process_events()
        self._status.setText(
            "Touch release: the stroke committed and the mouse brush cursor is ready."
        )

    def two_finger_pan(self) -> None:
        """Run a short two-finger gesture that navigates without painting."""
        if self._touch_active:
            self.touch_up()
        center = self._position().toPoint()
        start_left = center + QPointF(-30.0, 0.0).toPoint()
        start_right = center + QPointF(30.0, 0.0).toPoint()
        end_left = start_left + QPointF(15.0, 10.0).toPoint()
        end_right = start_right + QPointF(15.0, 10.0).toPoint()
        QTest.touchEvent(self._viewer, self._touch).press(
            0, start_left, self._viewer
        ).press(1, start_right, self._viewer).commit()
        QTest.touchEvent(self._viewer, self._touch).move(
            0, end_left, self._viewer
        ).move(1, end_right, self._viewer).commit()
        QTest.touchEvent(self._viewer, self._touch).release(
            0, end_left, self._viewer
        ).release(1, end_right, self._viewer).commit()
        self._process_events()
        self._status.setText("Two fingers: navigation won and no brush mark was made.")

    def mouse_move(self) -> None:
        """Simulate application-generated mouse motion after direct input."""
        position = self._position()
        global_position = QPointF(self._viewer.mapToGlobal(position.toPoint()))
        event = QMouseEvent(
            QEvent.Type.MouseMove,
            position,
            position,
            global_position,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.MouseEventSource.MouseEventSynthesizedByApplication,
        )
        QApplication.sendEvent(self._viewer, event)
        self._status.setText("Mouse activity: mouse ownership is active on the canvas.")

    def _send_tablet(
        self,
        event_type: QEvent.Type,
        *,
        pressure: float,
        buttons: Qt.MouseButton,
    ) -> None:
        """Send one synthetic tablet packet through CuteCanvas's normal QWidget surface."""
        QApplication.sendEvent(
            self._viewer,
            self._tablet_event(event_type, pressure=pressure, buttons=buttons),
        )
        self._process_events()

    def _tablet_event(
        self,
        event_type: QEvent.Type,
        *,
        pressure: float,
        buttons: Qt.MouseButton,
    ) -> QTabletEvent:
        """Construct a tablet event for the selected active pen end."""
        position = self._position()
        global_position = QPointF(self._viewer.mapToGlobal(position.toPoint()))
        return QTabletEvent(
            event_type,
            self._selected_device(),
            position,
            global_position,
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

    def _selected_device(self) -> QPointingDevice:
        """Return the synthetic pen end selected by the developer."""
        return self._eraser if self._device_selector.currentIndex() else self._pen

    def _position(self) -> QPointF:
        """Return the requested logical position inside the viewer."""
        return QPointF(float(self._x_slider.value()), float(self._y_slider.value()))

    def _pressure(self) -> float:
        """Return the pressure slider as a normalized tablet value."""
        return self._pressure_slider.value() / 100.0

    @staticmethod
    def _process_events() -> None:
        """Flush synthetic input so feedback updates immediately in the tutorial."""
        application = QApplication.instance()
        if application is not None:
            application.processEvents()


def build_touch_input_simulator(image: QImage) -> QWidget:
    """Build a no-hardware input laboratory around a public CuteCanvas instance."""
    viewer = build_touch_mask_editor(image)
    viewer.setObjectName("touchPenViewer")
    viewer.setMinimumSize(480, 360)

    device_selector = QComboBox()
    device_selector.addItems(("Pen tip", "Eraser end"))
    x_slider = _coordinate_slider("simulatedX", 240)
    y_slider = _coordinate_slider("simulatedY", 180)
    pressure_slider = _coordinate_slider("simulatedPressure", 50, maximum=100)
    status = QLabel(
        "Select a device and send events. Hover never changes the mask.",
    )
    status.setWordWrap(True)

    controls = QGroupBox("Synthetic pointer controls")
    form = QFormLayout(controls)
    form.addRow("Device", device_selector)
    form.addRow("X", x_slider)
    form.addRow("Y", y_slider)
    form.addRow("Pressure", pressure_slider)
    form.addRow(status)

    simulator = PointerSimulator(
        viewer,
        device_selector=device_selector,
        x_slider=x_slider,
        y_slider=y_slider,
        pressure_slider=pressure_slider,
        status=status,
    )
    button_specs = (
        ("penHover", "Pen hover", simulator.hover),
        ("penDown", "Pen down", simulator.pen_down),
        ("penMove", "Pen move", simulator.pen_move),
        ("penUp", "Pen up", simulator.pen_up),
        ("penLeave", "Leave proximity", simulator.leave_proximity),
        ("touchDown", "Touch down", simulator.touch_down),
        ("touchMove", "Touch move", simulator.touch_move),
        ("touchUp", "Touch up", simulator.touch_up),
        ("twoFingerPan", "Two-finger pan", simulator.two_finger_pan),
        ("mouseMove", "Return to mouse", simulator.mouse_move),
    )
    button_rows = QVBoxLayout()
    for object_name, label, callback in button_specs:
        button = QPushButton(label)
        button.setObjectName(object_name)
        button.clicked.connect(callback)
        button_rows.addWidget(button)
    form.addRow(button_rows)

    window = QWidget()
    window.setWindowTitle("CuteCanvas touch and pen simulator")
    layout = QHBoxLayout(window)
    layout.addWidget(viewer, 1)
    layout.addWidget(controls)
    window.resize(900, 560)
    window.setProperty("pointerSimulator", simulator)
    return window


def create_simulator_image() -> QImage:
    """Create a high-contrast canvas that makes brush feedback easy to inspect."""
    image = QImage(640, 480, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(235, 238, 242))
    painter = QPainter(image)
    painter.setPen(QPen(QColor(195, 201, 210), 1))
    for x in range(0, image.width(), 40):
        painter.drawLine(x, 0, x, image.height())
    for y in range(0, image.height(), 40):
        painter.drawLine(0, y, image.width(), y)
    painter.end()
    return image


def main() -> int:
    """Run the standalone synthetic touch and active-pen laboratory."""
    application = QApplication.instance() or QApplication(sys.argv)
    window = build_touch_input_simulator(create_simulator_image())
    window.show()
    return application.exec()


def _coordinate_slider(
    object_name: str,
    value: int,
    *,
    maximum: int = 480,
) -> QSlider:
    """Create one labeled horizontal simulator slider."""
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setObjectName(object_name)
    slider.setRange(0, maximum)
    slider.setValue(value)
    return slider


if __name__ == "__main__":
    raise SystemExit(main())
