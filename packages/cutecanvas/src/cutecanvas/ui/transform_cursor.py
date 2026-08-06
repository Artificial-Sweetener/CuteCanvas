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
"""Procedural operation cursors for direct affine manipulation."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath, QPen, QPixmap


class TransformCursorFactory:
    """Build and retain readable resize, skew, and rotation cursors."""

    def __init__(self) -> None:
        """Initialize an empty angle-bucketed cursor cache."""
        self._cache: dict[tuple[str, int], QCursor] = {}

    def resize(self, angle_degrees: float) -> QCursor:
        """Return a bidirectional arrow aligned to the active handle axis."""
        return self._cursor("resize", angle_degrees)

    def skew(self, angle_degrees: float) -> QCursor:
        """Return a bidirectional arrow aligned to the side tangent."""
        return self._cursor("skew", angle_degrees)

    def rotate(self, tangent_angle_degrees: float) -> QCursor:
        """Return restrained rotation feedback aligned to the nearest corner."""
        return self._cursor("rotate", tangent_angle_degrees)

    def _cursor(self, kind: str, angle_degrees: float) -> QCursor:
        """Resolve one procedural cursor from a stable one-degree bucket."""
        bucket = round(angle_degrees) % 180
        key = kind, bucket
        cursor = self._cache.get(key)
        if cursor is not None:
            return cursor
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if kind == "rotate":
            self._draw_rotation(painter, math.radians(bucket))
        else:
            self._draw_bidirectional(painter, math.radians(bucket))
        painter.end()
        cursor = QCursor(pixmap, 16, 16)
        self._cache[key] = cursor
        return cursor

    @classmethod
    def _draw_bidirectional(cls, painter: QPainter, angle: float) -> None:
        """Draw an outlined two-headed arrow through the cursor hotspot."""
        direction = QPointF(math.cos(angle), math.sin(angle))
        normal = QPointF(-direction.y(), direction.x())
        start = QPointF(16.0, 16.0) - direction * 10.0
        end = QPointF(16.0, 16.0) + direction * 10.0
        path = QPainterPath(start)
        path.lineTo(end)
        for tip, sign in ((start, 1.0), (end, -1.0)):
            base = tip + direction * (4.5 * sign)
            path.moveTo(tip)
            path.lineTo(base + normal * 3.0)
            path.moveTo(tip)
            path.lineTo(base - normal * 3.0)
        cls._stroke(painter, path)

    @classmethod
    def _draw_rotation(cls, painter: QPainter, angle: float) -> None:
        """Draw a short corner-oriented arc instead of a generic spin glyph."""
        painter.save()
        painter.translate(16.0, 16.0)
        painter.rotate(math.degrees(angle))
        painter.translate(-16.0, -16.0)
        path = QPainterPath()
        path.arcMoveTo(QRectF(10.0, 10.0, 12.0, 12.0), 30.0)
        path.arcTo(QRectF(10.0, 10.0, 12.0, 12.0), 30.0, 105.0)
        tip = path.currentPosition()
        path.moveTo(tip)
        path.lineTo(tip + QPointF(-0.5, -4.5))
        path.moveTo(tip)
        path.lineTo(tip + QPointF(4.0, -1.5))
        cls._stroke(painter, path)
        painter.restore()

    @staticmethod
    def _stroke(painter: QPainter, path: QPainterPath) -> None:
        """Draw a white interior with a dark one-pixel readability outline."""
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(20, 20, 20, 245), 3.5))
        painter.drawPath(path)
        painter.setPen(QPen(QColor(245, 245, 245, 255), 1.5))
        painter.drawPath(path)
