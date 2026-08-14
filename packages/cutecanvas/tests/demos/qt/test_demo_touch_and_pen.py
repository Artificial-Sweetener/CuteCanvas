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

"""Tests for the no-hardware touch and active-pen demonstration."""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from cutecanvas import CuteCanvas
from demonstration.touch_and_pen import build_touch_mask_editor
from demonstration.touch_and_pen_simulator import (
    build_touch_input_simulator,
    create_simulator_image,
)


def test_touch_mask_editor_mouse_touch_mouse_cursor_lifecycle(qapp) -> None:
    """The tutorial editor must restore its brush immediately after touch."""
    image = QImage(2048, 2048, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.white)
    viewer = build_touch_mask_editor(image)
    host = QWidget()
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    viewer.setParent(host)
    layout.addWidget(viewer)
    host.resize(500, 500)
    host.show()
    qapp.processEvents()
    touch_device = QTest.createTouchDevice()
    try:
        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=QPoint(80, 100))
        QTest.mouseMove(viewer, QPoint(180, 100))
        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=QPoint(180, 100))
        QTest.touchEvent(viewer, touch_device).press(
            0, QPoint(220, 200), viewer
        ).commit()
        QTest.touchEvent(viewer, touch_device).move(
            0, QPoint(320, 200), viewer
        ).commit()
        QTest.touchEvent(viewer, touch_device).release(
            0, QPoint(320, 200), viewer
        ).commit()
        qapp.processEvents()

        cursor_after_touch = viewer.cursor()
        assert cursor_after_touch.shape() != Qt.CursorShape.BlankCursor
        assert not cursor_after_touch.pixmap().isNull()

        window = host.windowHandle()
        assert window is not None
        QTest.mouseMove(window, viewer.mapTo(host, QPoint(380, 260)))
        qapp.processEvents()

        cursor_after_mouse = viewer.cursor()
        assert cursor_after_mouse.shape() != Qt.CursorShape.BlankCursor
        assert not cursor_after_mouse.pixmap().isNull()
    finally:
        host.close()
        viewer.deleteLater()
        host.deleteLater()
        qapp.processEvents()


def test_touch_and_pen_simulator_exercises_feedback_transitions(qapp) -> None:
    """Drive the tutorial controls through hover, touch, and mouse restoration."""
    window = build_touch_input_simulator(create_simulator_image())
    try:
        window.show()
        qapp.processEvents()
        viewer = window.findChild(CuteCanvas, "touchPenViewer")
        assert viewer is not None
        hover = window.findChild(QPushButton, "penHover")
        pen_leave = window.findChild(QPushButton, "penLeave")
        touch_down = window.findChild(QPushButton, "touchDown")
        touch_up = window.findChild(QPushButton, "touchUp")
        mouse_move = window.findChild(QPushButton, "mouseMove")
        assert hover is not None
        assert pen_leave is not None
        assert touch_down is not None
        assert touch_up is not None
        assert mouse_move is not None

        hover.click()
        assert viewer.cursor().shape() == Qt.CursorShape.BlankCursor
        pen_leave.click()
        assert viewer.cursor().shape() != Qt.CursorShape.BlankCursor
        touch_down.click()
        assert viewer.cursor().shape() == Qt.CursorShape.BlankCursor
        touch_up.click()
        assert viewer.cursor().shape() != Qt.CursorShape.BlankCursor
        mouse_move.click()

        assert viewer.cursor().shape() != Qt.CursorShape.BlankCursor
        cursor_image = viewer.cursor().pixmap().toImage()
        assert not cursor_image.isNull()
        opaque_values = [
            cursor_image.pixelColor(x_position, y_position).value()
            for y_position in range(cursor_image.height())
            for x_position in range(cursor_image.width())
            if cursor_image.pixelColor(x_position, y_position).alpha() >= 128
        ]
        assert opaque_values
        assert min(opaque_values) <= 32
        assert max(opaque_values) >= 223
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()
