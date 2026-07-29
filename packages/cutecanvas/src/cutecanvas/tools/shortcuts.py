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
"""Own document-history keyboard shortcuts for the editor surface."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QKeyEvent, QKeySequence


class EditorHistoryShortcuts:
    """Route standard Undo and Redo sequences to chronological history."""

    def __init__(
        self,
        *,
        undo: Callable[[], bool],
        redo: Callable[[], bool],
    ) -> None:
        """Bind the active-document history commands."""
        self._undo = undo
        self._redo = redo

    def handle(self, event: QKeyEvent) -> bool:
        """Execute a matched history command and consume its key event."""
        if event.matches(QKeySequence.StandardKey.Undo):
            self._undo()
        elif event.matches(QKeySequence.StandardKey.Redo):
            self._redo()
        else:
            return False
        event.accept()
        return True
