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

"""Shared high-contrast rendering policy for brush-size feedback."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

BRUSH_OUTLINE_PADDING = 4


def draw_brush_outline(
    painter: QPainter,
    ellipse: QRectF,
    color: QColor,
) -> None:
    """Draw a black/white/color ring visible over arbitrary image content."""
    path = QPainterPath()
    path.addEllipse(ellipse)
    draw_brush_path_outline(painter, path, color)


def draw_brush_path_outline(
    painter: QPainter,
    path: QPainterPath,
    color: QColor,
) -> None:
    """Draw one high-contrast brush-footprint path."""
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for ring_color, width in (
        (QColor(Qt.GlobalColor.black), 5.0),
        (QColor(Qt.GlobalColor.white), 3.0),
        (QColor(color), 1.0),
    ):
        pen = QPen(ring_color, width)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawPath(path)
