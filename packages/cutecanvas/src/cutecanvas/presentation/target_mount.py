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

"""Lightweight retained mount for one heavyweight CuteCanvas renderer."""

from __future__ import annotations

from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QWidget

from ..canvas import CuteCanvas


class CanvasTargetMount(QWidget):
    """Keep one heavyweight renderer parented while layouts move its host."""

    def __init__(self, canvas: CuteCanvas, parent: QWidget) -> None:
        """Parent the retained canvas once and fill this lightweight mount."""
        super().__init__(parent)
        self._canvas = canvas
        canvas.setParent(self)
        canvas.setGeometry(self.rect())
        canvas.show()

    @property
    def canvas(self) -> CuteCanvas:
        """Return the retained canvas hosted by this mount."""
        return self._canvas

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Keep the canvas aligned without reparenting its renderer state."""
        super().resizeEvent(event)
        self._canvas.setGeometry(self.rect())
