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

"""Manifest values for exact affine, projective, and piecewise mappings."""

from __future__ import annotations

from PySide6.QtCore import QPointF
from qpane.sdk.scene import (
    BilinearLayerTransform,
    LayerMapping,
    LayerTransform,
    PiecewiseLayerTransform,
    ProjectiveLayerTransform,
)


def encode_layer_mapping(mapping: LayerMapping) -> list[float] | dict[str, object]:
    """Encode one mapping without discarding projective coefficients."""
    if isinstance(mapping, BilinearLayerTransform):
        return {
            "kind": "bilinear",
            "source": [[point.x(), point.y()] for point in mapping.source_boundary],
            "target": [[point.x(), point.y()] for point in mapping.target_boundary],
        }
    if isinstance(mapping, PiecewiseLayerTransform):
        return {
            "kind": "piecewise",
            "source": [[point.x(), point.y()] for point in mapping.source_boundary],
            "target": [[point.x(), point.y()] for point in mapping.target_boundary],
        }
    if isinstance(mapping, ProjectiveLayerTransform):
        return list(mapping.coefficients)
    return [
        mapping.m11,
        mapping.m12,
        mapping.m21,
        mapping.m22,
        mapping.dx,
        mapping.dy,
    ]


def decode_layer_mapping(
    value: object,
    *,
    legacy_version_two: bool = False,
) -> LayerMapping:
    """Validate and decode one versioned manifest mapping value."""
    if isinstance(value, dict):
        if (
            legacy_version_two
            or set(value) != {"kind", "source", "target"}
            or value.get("kind") not in {"piecewise", "collapsed-piecewise", "bilinear"}
        ):
            raise ValueError("unsupported layer transform object")
        source = _decode_boundary(value.get("source"), name="source")
        target = _decode_boundary(value.get("target"), name="target")
        if value.get("kind") in {"collapsed-piecewise", "bilinear"}:
            if len(source) != 4 or len(target) != 4:
                raise ValueError(
                    "collapsed piecewise boundaries must contain four points"
                )
            return BilinearLayerTransform(
                (source[0], source[1], source[2], source[3]),
                (target[0], target[1], target[2], target[3]),
            )
        return PiecewiseLayerTransform(source, target)
    if not isinstance(value, list):
        raise TypeError("layer transform must be a list or object")
    if legacy_version_two:
        if len(value) != 4:
            raise ValueError("legacy layer transform must contain 4 values")
        return LayerTransform(
            m11=float(value[0]),
            m22=float(value[1]),
            dx=float(value[2]),
            dy=float(value[3]),
        )
    if len(value) == 6:
        return LayerTransform(*(float(item) for item in value))
    if len(value) == 9:
        return ProjectiveLayerTransform(*(float(item) for item in value))
    raise ValueError("layer transform must contain 6 or 9 values")


def _decode_boundary(value: object, *, name: str) -> tuple[QPointF, ...]:
    """Decode one finite piecewise boundary from JSON coordinate pairs."""
    if not isinstance(value, list):
        raise TypeError(f"piecewise {name} boundary must be a list")
    if not 4 <= len(value) <= 128:
        raise ValueError(f"piecewise {name} boundary must contain 4 to 128 points")
    points: list[QPointF] = []
    for item in value:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError(f"piecewise {name} points must contain two values")
        if any(
            isinstance(coordinate, bool) or not isinstance(coordinate, (int, float))
            for coordinate in item
        ):
            raise TypeError(f"piecewise {name} point coordinates must be numbers")
        points.append(QPointF(float(item[0]), float(item[1])))
    return tuple(points)


__all__ = ["decode_layer_mapping", "encode_layer_mapping"]
