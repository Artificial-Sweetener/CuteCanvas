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

"""Tests for the no-hardware touch and active-pen demonstration."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from examples.demonstration.touch_and_pen_simulator import (
    build_touch_input_simulator,
    create_simulator_image,
)
from qpane import QPane


def test_touch_and_pen_simulator_exercises_feedback_transitions(qapp) -> None:
    """Drive the tutorial controls through hover, touch, and mouse restoration."""
    window = build_touch_input_simulator(create_simulator_image())
    try:
        window.show()
        qapp.processEvents()
        viewer = window.findChild(QPane, "touchPenViewer")
        assert viewer is not None
        hover = window.findChild(QPushButton, "penHover")
        touch_down = window.findChild(QPushButton, "touchDown")
        touch_up = window.findChild(QPushButton, "touchUp")
        mouse_move = window.findChild(QPushButton, "mouseMove")
        assert hover is not None
        assert touch_down is not None
        assert touch_up is not None
        assert mouse_move is not None

        hover.click()
        assert viewer.cursor().shape() == Qt.CursorShape.BlankCursor
        touch_down.click()
        touch_up.click()
        mouse_move.click()

        assert viewer.cursor().shape() != Qt.CursorShape.BlankCursor
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()
