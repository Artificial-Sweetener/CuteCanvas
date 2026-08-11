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
"""Deterministic Qt event-loop observation for QPane tests."""

from __future__ import annotations

from collections.abc import Callable
from math import ceil

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication


def wait_until(
    application: QApplication,
    predicate: Callable[[], bool],
    *,
    failure_message: str,
    timeout_seconds: float = 5.0,
) -> None:
    """Run Qt delivery until one observable condition becomes true."""
    if timeout_seconds <= 0.0:
        raise ValueError("timeout_seconds must be positive")
    if predicate():
        return
    loop = QEventLoop()
    poll = QTimer()
    deadline = QTimer()
    deadline.setSingleShot(True)

    def inspect() -> None:
        """Quit once the observed condition resolves."""
        if predicate():
            loop.quit()

    poll.setInterval(1)
    poll.timeout.connect(inspect)
    deadline.timeout.connect(loop.quit)
    poll.start()
    deadline.start(ceil(timeout_seconds * 1000.0))
    loop.exec()
    poll.stop()
    deadline.stop()
    if not predicate():
        raise AssertionError(failure_message)
