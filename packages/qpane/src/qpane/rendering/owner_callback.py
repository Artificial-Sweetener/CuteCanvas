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

"""Coalesce lightweight maintenance callbacks on a Qt owner loop."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer


class OwnerCallback:
    """Own at most one queued callback for a QObject lifetime."""

    def __init__(self, owner: QObject) -> None:
        """Bind the callback timer to ``owner``."""
        self._timer = QTimer(owner)
        self._timer.setSingleShot(True)
        self._callback: Callable[[], None] | None = None
        self._timer.timeout.connect(self._deliver)

    @property
    def pending(self) -> bool:
        """Return whether a callback is queued."""
        return self._callback is not None

    def schedule(self, callback: Callable[[], None]) -> None:
        """Queue ``callback`` once on the owner event loop."""
        if self._callback is not None:
            return
        self._callback = callback
        self._timer.start(0)

    def cancel(self) -> None:
        """Discard a pending callback."""
        self._timer.stop()
        self._callback = None

    def _deliver(self) -> None:
        """Clear pending state before invoking the callback."""
        callback = self._callback
        self._callback = None
        if callback is not None:
            callback()
