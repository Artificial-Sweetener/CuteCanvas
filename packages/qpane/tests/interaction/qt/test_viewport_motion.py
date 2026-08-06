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

"""Tests for transient kinetic viewport motion ownership."""

from PySide6.QtCore import QObject, QPointF
from qpane.rendering.viewport_motion import ViewportMotionController


def test_inertia_advances_pan_and_decelerates(qapp) -> None:
    parent = QObject()
    pan = QPointF()

    def apply_pan(value: QPointF) -> None:
        nonlocal pan
        pan = QPointF(value)

    motion = ViewportMotionController(
        get_pan=lambda: QPointF(pan),
        apply_pan=apply_pan,
        parent=parent,
    )

    assert motion.start(QPointF(1000.0, 0.0), deceleration=500.0)
    assert motion.advance(0.05)

    assert pan == QPointF(50.0, 0.0)
    assert motion.active
    motion.stop()


def test_inertia_stops_when_pan_is_clamped(qapp) -> None:
    parent = QObject()
    pan = QPointF()
    motion = ViewportMotionController(
        get_pan=lambda: QPointF(pan),
        apply_pan=lambda _value: None,
        parent=parent,
    )

    assert motion.start(QPointF(800.0, 0.0), deceleration=500.0)

    assert not motion.advance(0.016)
    assert not motion.active
