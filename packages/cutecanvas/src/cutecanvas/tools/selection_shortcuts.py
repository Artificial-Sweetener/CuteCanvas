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
"""Route selection-authoritative keyboard commands independently of tools."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent


class EditorSelectionShortcuts:
    """Clear selected pixels whenever the active document owns a selection."""

    def __init__(
        self,
        *,
        has_selection: Callable[[], bool],
        clear_selected_pixels: Callable[[], bool],
    ) -> None:
        """Bind authoritative selection state and pixel-edit command owners."""

        self._has_selection = has_selection
        self._clear_selected_pixels = clear_selected_pixels

    def handle(self, event: QKeyEvent) -> bool:
        """Consume Delete through selection ownership when a selection exists."""

        if event.key() != Qt.Key.Key_Delete or not self._has_selection():
            return False
        if not self._clear_selected_pixels():
            return False
        event.accept()
        return True


__all__ = ["EditorSelectionShortcuts"]
