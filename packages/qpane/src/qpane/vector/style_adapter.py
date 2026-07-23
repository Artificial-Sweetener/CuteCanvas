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
"""Single Qt style adaptation boundary for vector rendering and geometry."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPainterPathStroker, QPen

from .public import VectorStrokeCap, VectorStrokeJoin, VectorStyle


def brush_for_style(style: VectorStyle) -> QBrush:
    """Return the detached Qt brush for one semantic style."""
    return (
        QBrush(Qt.BrushStyle.NoBrush)
        if style.fill is None
        else QBrush(QColor(style.fill))
    )


def pen_for_style(style: VectorStyle) -> QPen:
    """Return the detached Qt pen for one semantic style."""
    if style.stroke is None or style.stroke_width <= 0.0:
        return QPen(Qt.PenStyle.NoPen)
    pen = QPen(QColor(style.stroke), style.stroke_width)
    pen.setJoinStyle(join_style(style.join))
    pen.setCapStyle(cap_style(style.cap))
    if style.dash_pattern:
        pen.setDashPattern(list(style.dash_pattern))
    return pen


def configure_stroker(stroker: QPainterPathStroker, style: VectorStyle) -> None:
    """Apply the same semantic stroke geometry used by the render pen."""
    stroker.setWidth(style.stroke_width)
    stroker.setJoinStyle(join_style(style.join))
    stroker.setCapStyle(cap_style(style.cap))
    if style.dash_pattern:
        stroker.setDashPattern(list(style.dash_pattern))


def join_style(join: VectorStrokeJoin) -> Qt.PenJoinStyle:
    """Map a durable join into Qt geometry."""
    return {
        VectorStrokeJoin.MITER: Qt.PenJoinStyle.MiterJoin,
        VectorStrokeJoin.ROUND: Qt.PenJoinStyle.RoundJoin,
        VectorStrokeJoin.BEVEL: Qt.PenJoinStyle.BevelJoin,
    }[join]


def cap_style(cap: VectorStrokeCap) -> Qt.PenCapStyle:
    """Map a durable cap into Qt geometry."""
    return {
        VectorStrokeCap.FLAT: Qt.PenCapStyle.FlatCap,
        VectorStrokeCap.ROUND: Qt.PenCapStyle.RoundCap,
        VectorStrokeCap.SQUARE: Qt.PenCapStyle.SquareCap,
    }[cap]
