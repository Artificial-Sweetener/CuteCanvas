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

"""Shared visual primitives for affine manipulation handles."""

from __future__ import annotations

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QPainter, QPen

AFFINE_HANDLE_RADIUS = 4.0


def draw_affine_handle(
    painter: QPainter,
    point: QPointF,
    *,
    emphasized: bool = False,
    enabled: bool = True,
) -> None:
    """Draw one Transform-style circular handle using the current outline pen."""
    radius = AFFINE_HANDLE_RADIUS + (1.0 if emphasized else 0.0)
    painter.setBrush(QColor(238, 242, 247, 245) if enabled else QColor(90, 90, 90, 225))
    painter.drawEllipse(point, radius, radius)
    if not enabled:
        painter.save()
        pen = QPen(QColor(238, 242, 247, 245), 1.5)
        pen.setCosmetic(True)
        painter.setPen(pen)
        inset = radius * 0.55
        painter.drawLine(
            QPointF(point.x() - inset, point.y() - inset),
            QPointF(point.x() + inset, point.y() + inset),
        )
        painter.drawLine(
            QPointF(point.x() - inset, point.y() + inset),
            QPointF(point.x() + inset, point.y() - inset),
        )
        painter.restore()


__all__ = ["AFFINE_HANDLE_RADIUS", "draw_affine_handle"]
