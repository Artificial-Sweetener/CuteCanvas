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
"""Validated archive values for typed composition layer effects."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QPointF

from qpane.sdk.scene import LayerEffectReference, LayerTransform

from ..document.canvas_crop import CanvasCropEffect
from ..resources import ProjectResourceReference
from ..vector.effects import VectorMaskEffect


def encode_layer_effect(effect: LayerEffectReference) -> dict[str, object]:
    """Encode one supported typed composition layer effect."""
    if isinstance(effect, CanvasCropEffect):
        return {
            "kind": effect.kind,
            "points": [[point.x(), point.y()] for point in effect.points],
        }
    if not isinstance(effect, VectorMaskEffect):
        raise TypeError(f"unsupported layer effect: {type(effect)!r}")
    transform = effect.transform
    return {
        "kind": effect.kind,
        "source": {
            "kind": effect.source.kind,
            "resource_id": str(effect.source.resource_id),
        },
        "transform": [
            transform.m11,
            transform.m12,
            transform.m21,
            transform.m22,
            transform.dx,
            transform.dy,
        ],
        "object_ids": [str(object_id) for object_id in effect.object_ids],
        "inverted": effect.inverted,
    }


def decode_layer_effect(item: object) -> LayerEffectReference:
    """Validate and decode one supported typed composition layer effect."""
    if not isinstance(item, dict):
        raise TypeError("layer effects must be objects")
    kind = item.get("kind")
    if kind == "canvas-crop":
        return _decode_canvas_crop(item)
    if kind == "vector-mask":
        return _decode_vector_mask(item)
    raise ValueError(f"unsupported layer effect kind: {kind}")


def _decode_canvas_crop(item: dict[object, object]) -> CanvasCropEffect:
    """Decode one inline target-local crop polygon."""
    points = item.get("points")
    if not isinstance(points, list) or len(points) < 3:
        raise ValueError("canvas crop points must contain at least three pairs")
    decoded = []
    for point in points:
        if not isinstance(point, list) or len(point) != 2:
            raise ValueError("canvas crop points must contain coordinate pairs")
        decoded.append(QPointF(float(point[0]), float(point[1])))
    return CanvasCropEffect(tuple(decoded))


def _decode_vector_mask(item: dict[object, object]) -> VectorMaskEffect:
    """Decode one vector-resource-backed target-local mask."""
    source = item.get("source")
    transform = item.get("transform")
    object_ids = item.get("object_ids", [])
    if not isinstance(source, dict) or source.get("kind") not in {
        "project-resource",
        "vector",
    }:
        raise ValueError("vector masks require a vector source")
    if not isinstance(transform, list) or len(transform) != 6:
        raise ValueError("vector mask transforms must contain six values")
    if not isinstance(object_ids, list):
        raise TypeError("vector mask object IDs must be a list")
    return VectorMaskEffect(
        ProjectResourceReference(uuid.UUID(str(source["resource_id"]))),
        LayerTransform(*(float(value) for value in transform)),
        tuple(uuid.UUID(str(value)) for value in object_ids),
        bool(item.get("inverted", False)),
    )


__all__ = ["decode_layer_effect", "encode_layer_effect"]
