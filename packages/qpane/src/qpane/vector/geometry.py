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
"""Qt-derived path geometry and exact local hit testing for vector objects."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainterPath, QPainterPathStroker

from .model import VectorObject
from .public import (
    VectorFillRule,
    VectorObjectKind,
    VectorPathCommandKind,
    VectorShapeKind,
)
from .style_adapter import configure_stroker
from .text_layout import SemanticTextLayoutCache, shape_text


def object_local_path(
    item: VectorObject,
    text_layouts: SemanticTextLayoutCache | None = None,
) -> QPainterPath:
    """Return one object's untransformed derived painter path."""
    if item.kind is VectorObjectKind.TEXT and item.text is not None:
        bounds = QRectF(*item.local_bounds)
        return QPainterPath(
            (
                shape_text(
                    item.text,
                    bounds,
                    include_picture=False,
                    include_painted=False,
                    include_carets=False,
                    include_diagnostics=False,
                )
                if text_layouts is None
                else text_layouts.outline_product(item.text, bounds)
            ).outline
        )
    path = QPainterPath()
    x, y, width, height = item.local_bounds
    if item.shape_kind is VectorShapeKind.RECTANGLE:
        path.addRect(QRectF(x, y, width, height))
    elif item.shape_kind is VectorShapeKind.ELLIPSE:
        path.addEllipse(QRectF(x, y, width, height))
    else:
        _append_commands(path, item)
    path.setFillRule(
        Qt.FillRule.OddEvenFill
        if item.style.fill_rule is VectorFillRule.EVEN_ODD
        else Qt.FillRule.WindingFill
    )
    return path


def object_path(
    item: VectorObject,
    text_layouts: SemanticTextLayoutCache | None = None,
) -> QPainterPath:
    """Return one object's transformed fill geometry."""
    return item.transform.to_qtransform().map(object_local_path(item, text_layouts))


def object_contains(
    item: VectorObject,
    point: QPointF,
    text_layouts: SemanticTextLayoutCache | None = None,
) -> bool:
    """Hit test fill and stroke geometry without reading raster alpha."""
    local_path = object_local_path(item, text_layouts)
    path = item.transform.to_qtransform().map(local_path)
    if item.kind is VectorObjectKind.TEXT:
        return path.contains(point)
    if item.style.fill is not None and path.contains(point):
        return True
    if item.style.stroke is None or item.style.stroke_width <= 0.0:
        return False
    stroker = QPainterPathStroker()
    configure_stroker(stroker, item.style)
    stroke = item.transform.to_qtransform().map(stroker.createStroke(local_path))
    return stroke.contains(point)


def _append_commands(path: QPainterPath, item: VectorObject) -> None:
    """Replay durable path commands into a derived Qt path."""
    for command in item.path:
        points = command.points
        if command.kind is VectorPathCommandKind.MOVE:
            path.moveTo(points[0])
        elif command.kind is VectorPathCommandKind.LINE:
            path.lineTo(points[0])
        elif command.kind is VectorPathCommandKind.QUADRATIC:
            path.quadTo(points[0], points[1])
        elif command.kind is VectorPathCommandKind.CUBIC:
            path.cubicTo(points[0], points[1], points[2])
        elif command.kind is VectorPathCommandKind.CLOSE:
            path.closeSubpath()
