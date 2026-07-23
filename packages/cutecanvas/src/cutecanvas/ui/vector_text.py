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
"""Canvas feedback rendering for in-place semantic vector text."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen

from ..vector.text_edit import VectorTextOverlayState


class VectorTextOverlayRenderer:
    """Draw a quiet text box and visible insertion caret without owning state."""

    def draw(self, painter: QPainter, state: object | None) -> None:
        """Draw detached text editing feedback when a session is active."""
        if not isinstance(state, VectorTextOverlayState):
            return
        painter.save()
        try:
            box_pen = QPen(QColor(95, 170, 235, 190), 1.0, Qt.PenStyle.DashLine)
            box_pen.setCosmetic(True)
            painter.setPen(box_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolygon(state.box)
            caret_pen = QPen(QColor(245, 245, 245, 255), 1.5)
            caret_pen.setCosmetic(True)
            painter.setPen(caret_pen)
            painter.drawLine(state.caret)
        finally:
            painter.restore()
