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
"""Explicit semantic-text conversion into durable painted vector paths."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath
from qpane.sdk.vector import (
    SemanticTextLayoutCache,
    VectorDocument,
    VectorFillRule,
    VectorObject,
    VectorObjectKind,
    VectorPathCommand,
    VectorPathCommandKind,
    VectorStyle,
)


@dataclass(frozen=True, slots=True)
class VectorTextPathConversion:
    """Carry one detached replacement document and its created object IDs."""

    document: VectorDocument
    path_ids: tuple[uuid.UUID, ...]


def build_text_path_conversion(
    document: VectorDocument,
    object_id: uuid.UUID,
) -> VectorTextPathConversion | None:
    """Build exact painted outlines without reading or mutating domain state."""
    item = document.object(object_id)
    if item is None or item.kind is not VectorObjectKind.TEXT or item.text is None:
        return None
    product = SemanticTextLayoutCache(0).painted_outline_product(
        item.text,
        QRectF(*item.local_bounds),
    )
    replacements = tuple(
        _outline_object(item, color, path)
        for color, path in product.painted_outlines
        if not path.isEmpty()
    )
    if not replacements:
        return None
    objects = list(document.objects)
    index = objects.index(item)
    objects[index : index + 1] = replacements
    replacement = replace(
        document,
        objects=tuple(objects),
        revision=document.revision + 1,
    )
    return VectorTextPathConversion(
        replacement,
        tuple(item.object_id for item in replacements),
    )


def _outline_object(
    item: VectorObject, color: QColor, path: QPainterPath
) -> VectorObject:
    """Create one durable painted path retaining the text object's transform."""
    commands = _path_commands(path)
    bounds = path.boundingRect()
    return VectorObject(
        uuid.uuid4(),
        VectorObjectKind.PATH,
        (bounds.x(), bounds.y(), bounds.width(), bounds.height()),
        item.transform,
        VectorStyle(
            fill=color,
            stroke=None,
            stroke_width=0.0,
            opacity=item.style.opacity,
            fill_rule=(
                VectorFillRule.EVEN_ODD
                if path.fillRule() is Qt.FillRule.OddEvenFill
                else VectorFillRule.WINDING
            ),
        ),
        path=commands,
    )


def _path_commands(path: QPainterPath) -> tuple[VectorPathCommand, ...]:
    """Translate an exact Qt outline into durable move/line/cubic commands."""
    commands: list[VectorPathCommand] = []
    index = 0
    element_count = path.elementCount()
    element_at = path.elementAt
    append = commands.append
    create = VectorPathCommand._from_finite_points
    point = QPointF
    move = VectorPathCommandKind.MOVE
    line = VectorPathCommandKind.LINE
    cubic = VectorPathCommandKind.CUBIC
    move_element = QPainterPath.ElementType.MoveToElement
    line_element = QPainterPath.ElementType.LineToElement
    curve_element = QPainterPath.ElementType.CurveToElement
    while index < element_count:
        element = element_at(index)
        first = point(element.x, element.y)
        if element.type == move_element:
            append(create(move, (first,)))
            index += 1
        elif element.type == line_element:
            append(create(line, (first,)))
            index += 1
        elif element.type == curve_element:
            if index + 2 >= element_count:
                raise ValueError("Qt text outline ended inside a cubic segment")
            control_two = element_at(index + 1)
            end = element_at(index + 2)
            append(
                create(
                    cubic,
                    (
                        first,
                        point(control_two.x, control_two.y),
                        point(end.x, end.y),
                    ),
                )
            )
            index += 3
        else:
            raise ValueError("unexpected standalone Qt curve-data element")
    if not commands:
        raise ValueError("text outline conversion requires painted glyphs")
    return tuple(commands)
