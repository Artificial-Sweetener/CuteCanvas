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

"""Own deterministic shutdown at the QPane widget-lifetime boundary."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject


class ViewerLifetime(QObject):
    """Run viewer shutdown once before close or deferred Qt destruction."""

    def __init__(self, owner: QObject, shutdown: Callable[[], None]) -> None:
        """Install lifetime observation on ``owner``."""
        super().__init__(owner)
        self._shutdown = shutdown
        self._closed = False
        owner.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Complete shutdown before Qt accepts a terminal owner event."""
        if event.type() in {
            QEvent.Type.Close,
            QEvent.Type.DeferredDelete,
        }:
            self._close()
        return super().eventFilter(watched, event)

    def _close(self) -> None:
        """Invoke the owned shutdown callback exactly once."""
        if self._closed:
            return
        self._closed = True
        self._shutdown()


__all__ = ["ViewerLifetime"]
