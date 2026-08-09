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
"""Validated manifest conversion for layer manipulation geometry."""

from __future__ import annotations

from qpane.sdk.scene import RasterBounds

from ..composition.geometry_policy import LayerGeometryMode, LayerGeometryPolicy

_MAX_BOUNDARY_POINTS = 128


def encode_layer_geometry(policy: LayerGeometryPolicy) -> dict[str, object]:
    """Encode one explicit manipulation-geometry policy."""
    bounds = policy.custom_bounds
    return {
        "mode": policy.mode.value,
        "custom_bounds": (
            None
            if bounds is None
            else [bounds.x, bounds.y, bounds.width, bounds.height]
        ),
        "custom_boundary": (
            None
            if policy.custom_boundary is None
            else [list(point) for point in policy.custom_boundary]
        ),
    }


def decode_layer_geometry(value: object) -> LayerGeometryPolicy:
    """Decode one policy or return the content-tight default for older archives."""
    if value is None:
        return LayerGeometryPolicy()
    if not isinstance(value, dict):
        raise TypeError("layer geometry must be an object")
    mode = LayerGeometryMode(str(value.get("mode", LayerGeometryMode.CONTENT.value)))
    encoded_bounds = value.get("custom_bounds")
    encoded_boundary = value.get("custom_boundary")
    bounds = None
    if encoded_bounds is not None:
        if not isinstance(encoded_bounds, list) or len(encoded_bounds) != 4:
            raise ValueError("custom layer geometry must contain four values")
        bounds = RasterBounds(*(int(component) for component in encoded_bounds))
    boundary = None
    if encoded_boundary is not None:
        if (
            not isinstance(encoded_boundary, list)
            or not 3 <= len(encoded_boundary) <= _MAX_BOUNDARY_POINTS
        ):
            raise ValueError("custom layer boundary must contain 3 to 128 points")
        boundary = tuple(
            (float(point[0]), float(point[1]))
            for point in encoded_boundary
            if isinstance(point, list) and len(point) == 2
        )
        if len(boundary) != len(encoded_boundary):
            raise ValueError("custom layer boundary points must contain two values")
    return LayerGeometryPolicy(mode, bounds, boundary)
