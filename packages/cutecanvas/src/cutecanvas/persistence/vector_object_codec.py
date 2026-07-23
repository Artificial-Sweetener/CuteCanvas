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
"""Validated JSON values for source-neutral QPane vector objects."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor
from qpane.sdk.scene import LayerTransform
from qpane.sdk.vector import (
    VectorFillRule,
    VectorObject,
    VectorObjectKind,
    VectorParagraphStyle,
    VectorPathCommand,
    VectorPathCommandKind,
    VectorShapeKind,
    VectorStrokeCap,
    VectorStrokeJoin,
    VectorStyle,
    VectorTextAlignment,
    VectorTextContent,
    VectorTextDirection,
    VectorTextSpan,
    VectorTextStyle,
)

MAX_VECTOR_TEXT_CODEPOINTS = 4_000_000
MAX_VECTOR_TEXT_SPANS = 100_000


def encode_vector_object(item: VectorObject) -> dict[str, object]:
    """Return one stable vector object's serializable semantic values."""
    transform = item.transform
    style = item.style
    return {
        "object_id": str(item.object_id),
        "kind": item.kind.value,
        "bounds": list(item.local_bounds),
        "transform": [
            transform.m11,
            transform.m12,
            transform.m21,
            transform.m22,
            transform.dx,
            transform.dy,
        ],
        "style": {
            "fill": _encode_color(style.fill),
            "stroke": _encode_color(style.stroke),
            "stroke_width": style.stroke_width,
            "opacity": style.opacity,
            "join": style.join.value,
            "cap": style.cap.value,
            "dash_pattern": list(style.dash_pattern),
            "fill_rule": style.fill_rule.value,
        },
        "shape_kind": None if item.shape_kind is None else item.shape_kind.value,
        "path": [
            {
                "kind": command.kind.value,
                "points": [[point.x(), point.y()] for point in command.points],
            }
            for command in item.path
        ],
        "text": None if item.text is None else _encode_vector_text(item.text),
    }


def decode_vector_object(item: object) -> tuple[VectorObject, int]:
    """Validate one serialized vector object and return its point count."""
    if not isinstance(item, dict):
        raise TypeError("vector object entries must be objects")
    bounds_values = item.get("bounds")
    transform_values = item.get("transform")
    style_values = item.get("style")
    path_values = item.get("path", [])
    if not isinstance(bounds_values, list) or len(bounds_values) != 4:
        raise ValueError("vector object bounds must contain four values")
    if not isinstance(transform_values, list) or len(transform_values) != 6:
        raise ValueError("vector object transform must contain six values")
    if not isinstance(style_values, dict):
        raise TypeError("vector object style must be an object")
    if not isinstance(path_values, list):
        raise TypeError("vector object path must be a list")
    commands: list[VectorPathCommand] = []
    point_count = 0
    for command_value in path_values:
        if not isinstance(command_value, dict):
            raise TypeError("vector path commands must be objects")
        points_value = command_value.get("points", [])
        if not isinstance(points_value, list):
            raise TypeError("vector command points must be a list")
        points = []
        for point_value in points_value:
            if not isinstance(point_value, list) or len(point_value) != 2:
                raise ValueError("vector points must contain two values")
            points.append(QPointF(float(point_value[0]), float(point_value[1])))
        point_count += len(points)
        commands.append(
            VectorPathCommand(
                VectorPathCommandKind(str(command_value["kind"])),
                tuple(points),
            )
        )
    style = VectorStyle(
        fill=_decode_color(style_values.get("fill")),
        stroke=_decode_color(style_values.get("stroke")),
        stroke_width=float(style_values["stroke_width"]),
        opacity=float(style_values["opacity"]),
        join=VectorStrokeJoin(str(style_values["join"])),
        cap=VectorStrokeCap(str(style_values["cap"])),
        dash_pattern=tuple(float(value) for value in style_values["dash_pattern"]),
        fill_rule=VectorFillRule(str(style_values["fill_rule"])),
    )
    shape_value = item.get("shape_kind")
    return (
        VectorObject(
            object_id=uuid.UUID(str(item["object_id"])),
            kind=VectorObjectKind(str(item["kind"])),
            local_bounds=tuple(float(value) for value in bounds_values),
            transform=LayerTransform(*(float(value) for value in transform_values)),
            style=style,
            shape_kind=(
                None if shape_value is None else VectorShapeKind(str(shape_value))
            ),
            path=tuple(commands),
            text=_decode_vector_text(item.get("text")),
        ),
        point_count,
    )


def _encode_vector_text(content: VectorTextContent) -> dict[str, object]:
    """Return serializable Unicode, character, and paragraph semantics."""
    return {
        "value": content.text,
        "style": _encode_vector_text_style(content.style),
        "spans": [
            {
                "start": span.start,
                "length": span.length,
                "style": _encode_vector_text_style(span.style),
            }
            for span in content.spans
        ],
        "paragraph": {
            "alignment": content.paragraph.alignment.value,
            "direction": content.paragraph.direction.value,
            "line_height": content.paragraph.line_height,
        },
    }


def _encode_vector_text_style(style: VectorTextStyle) -> dict[str, object]:
    """Return serializable semantic font request values."""
    return {
        "families": list(style.families),
        "font_size": style.font_size,
        "weight": style.weight,
        "italic": style.italic,
        "letter_spacing": style.letter_spacing,
        "color": _encode_color(style.color),
    }


def _decode_vector_text(item: object) -> VectorTextContent | None:
    """Validate and decode one optional semantic text payload."""
    if item is None:
        return None
    if not isinstance(item, dict):
        raise TypeError("vector text must be an object or null")
    value = item.get("value")
    spans_value = item.get("spans")
    paragraph_value = item.get("paragraph")
    if not isinstance(value, str):
        raise TypeError("vector text value must be a string")
    if len(value) > MAX_VECTOR_TEXT_CODEPOINTS:
        raise ValueError("vector text exceeds archive character limit")
    if not isinstance(spans_value, list):
        raise TypeError("vector text spans must be a list")
    if len(spans_value) > MAX_VECTOR_TEXT_SPANS:
        raise ValueError("vector text exceeds archive span limit")
    if not isinstance(paragraph_value, dict):
        raise TypeError("vector text paragraph must be an object")
    spans: list[VectorTextSpan] = []
    for span_value in spans_value:
        if not isinstance(span_value, dict):
            raise TypeError("vector text spans must be objects")
        spans.append(
            VectorTextSpan(
                int(span_value["start"]),
                int(span_value["length"]),
                _decode_vector_text_style(span_value.get("style")),
            )
        )
    return VectorTextContent(
        value,
        _decode_vector_text_style(item.get("style")),
        tuple(spans),
        VectorParagraphStyle(
            VectorTextAlignment(str(paragraph_value["alignment"])),
            VectorTextDirection(str(paragraph_value["direction"])),
            float(paragraph_value["line_height"]),
        ),
    )


def _decode_vector_text_style(item: object) -> VectorTextStyle:
    """Validate and decode one semantic font request."""
    if not isinstance(item, dict):
        raise TypeError("vector text style must be an object")
    families = item.get("families")
    if not isinstance(families, list) or any(
        not isinstance(family, str) for family in families
    ):
        raise TypeError("vector text families must be a list of strings")
    color = _decode_color(item.get("color"))
    if color is None:
        raise ValueError("vector text color must not be null")
    return VectorTextStyle(
        tuple(families),
        float(item["font_size"]),
        int(item["weight"]),
        bool(item["italic"]),
        float(item["letter_spacing"]),
        color,
    )


def _encode_color(color: QColor | None) -> list[int] | None:
    """Return detached RGBA channels for one optional semantic color."""
    return None if color is None else list(color.getRgb())


def _decode_color(item: object) -> QColor | None:
    """Validate and decode one optional RGBA color value."""
    if item is None:
        return None
    if not isinstance(item, list) or len(item) != 4:
        raise ValueError("vector colors must contain four channels")
    channels = tuple(int(value) for value in item)
    if any(value < 0 or value > 255 for value in channels):
        raise ValueError("vector color channels must be between 0 and 255")
    return QColor(*channels)
