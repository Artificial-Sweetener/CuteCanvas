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
"""Focused QWidget surfaces for built-in multi-target presentations."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from PySide6.QtWidgets import QTabWidget, QWidget

from .target_mount import CanvasTargetMount


class TabbedCanvasSurface(QTabWidget):
    """Present independent native-size canvases as host-style inspection tabs."""

    def __init__(
        self,
        entries: tuple[tuple[uuid.UUID, str, CanvasTargetMount], ...],
        activated: Callable[[uuid.UUID], None],
        parent: QWidget,
    ) -> None:
        """Install stable target tabs and activation routing."""
        super().__init__(parent)
        self._target_ids = tuple(entry[0] for entry in entries)
        self._activated = activated
        self.setDocumentMode(True)
        self.setMovable(False)
        for _target_id, title, canvas in entries:
            self.addTab(canvas, title)
        self.currentChanged.connect(self._current_changed)

    def activate(self, target_id: uuid.UUID | None) -> None:
        """Select a target tab without rebuilding its renderer."""
        if target_id in self._target_ids:
            self.setCurrentIndex(self._target_ids.index(target_id))

    def _current_changed(self, index: int) -> None:
        """Publish deliberate tab selection."""
        if 0 <= index < len(self._target_ids):
            self._activated(self._target_ids[index])
