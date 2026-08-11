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
from time import monotonic

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


def wait_until(
    application: QApplication,
    predicate: Callable[[], bool],
    *,
    failure_message: str,
    timeout_seconds: float = 5.0,
) -> None:
    """Process Qt events until one observable condition becomes true."""
    deadline = monotonic() + timeout_seconds
    while not predicate() and monotonic() < deadline:
        application.processEvents()
        QTest.qWait(1)
    if not predicate():
        raise AssertionError(failure_message)
