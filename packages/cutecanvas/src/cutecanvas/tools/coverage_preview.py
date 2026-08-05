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

"""Render clipped coverage boundaries as consistently visible feedback."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen


def draw_clipped_marching_ants(
    painter: QPainter,
    path: QPainterPath,
    *,
    dark_color: QColor | Qt.GlobalColor = Qt.GlobalColor.black,
) -> None:
    """Draw a two-tone cosmetic boundary with a configurable dark phase."""
    painter.save()
    try:
        painter.setClipPath(path, Qt.ClipOperation.IntersectClip)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        dark = QPen(QColor(dark_color), 2.0, Qt.PenStyle.SolidLine)
        dark.setCosmetic(True)
        painter.setPen(dark)
        painter.drawPath(path)
        light = QPen(Qt.GlobalColor.white, 2.0, Qt.PenStyle.DashLine)
        light.setCosmetic(True)
        painter.setPen(light)
        painter.drawPath(path)
    finally:
        painter.restore()


__all__ = ["draw_clipped_marching_ants"]
