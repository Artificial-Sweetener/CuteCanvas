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

"""Nearest-neighbor coverage resampling through joined-edge layer geometry."""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF
from qpane.sdk.scene import BilinearLayerTransform, RasterBounds

from cutecanvas.coverage import CoverageSnapshot
from cutecanvas.types import RasterExtentPolicy

from .bilinear_coordinates import (
    bilinear_coordinates,
    inverse_bilinear_source_row,
)


def project_bilinear_coverage(
    snapshot: CoverageSnapshot,
    mapping: BilinearLayerTransform,
    *,
    canvas_x: float,
    canvas_y: float,
    canvas_width: int,
    canvas_height: int,
) -> np.ndarray:
    """Project source pixels through one full-source joined-edge mapping."""
    result = np.zeros((canvas_height, canvas_width), dtype=np.uint8)
    bounds = snapshot.bounds
    if bounds is None:
        return result
    apex = mapping.target_boundary[0]
    right = mapping.target_boundary[2] - apex
    left = mapping.target_boundary[3] - apex
    determinant = left.x() * right.y() - left.y() * right.x()
    if abs(determinant) <= 1e-18:
        return result
    target_left = max(
        0,
        math.floor(min(point.x() for point in mapping.target_boundary) - canvas_x),
    )
    target_right = min(
        canvas_width,
        math.ceil(max(point.x() for point in mapping.target_boundary) - canvas_x),
    )
    target_top = max(
        0,
        math.floor(min(point.y() for point in mapping.target_boundary) - canvas_y),
    )
    target_bottom = min(
        canvas_height,
        math.ceil(max(point.y() for point in mapping.target_boundary) - canvas_y),
    )
    if target_left >= target_right or target_top >= target_bottom:
        return result
    scene_x = canvas_x + np.arange(target_left, target_right, dtype=np.float64) + 0.5
    source = mapping.source_boundary
    for target_y in range(target_top, target_bottom):
        scene_y = canvas_y + target_y + 0.5
        relative_x = scene_x - apex.x()
        relative_y = scene_y - apex.y()
        left_weight = (relative_x * right.y() - relative_y * right.x()) / determinant
        right_weight = (left.x() * relative_y - left.y() * relative_x) / determinant
        v = left_weight + right_weight
        valid = (left_weight >= 0.0) & (right_weight >= 0.0) & (v <= 1.0) & (v > 1e-12)
        if not np.any(valid):
            continue
        u = np.zeros_like(v)
        np.divide(right_weight, v, out=u, where=valid)
        source_x, source_y = bilinear_coordinates(source, u, v)
        pixel_x = np.floor(source_x).astype(np.int64) - bounds.x
        pixel_y = np.floor(source_y).astype(np.int64) - bounds.y
        valid &= (
            (pixel_x >= 0)
            & (pixel_x < bounds.width)
            & (pixel_y >= 0)
            & (pixel_y < bounds.height)
        )
        if np.any(valid):
            destination = result[target_y, target_left:target_right]
            destination[valid] = snapshot.pixels[pixel_y[valid], pixel_x[valid]]
    return result


def project_scene_coverage_to_bilinear_layer(
    snapshot: CoverageSnapshot,
    mapping: BilinearLayerTransform,
    *,
    layer_bounds: RasterBounds | None,
    extent_policy: RasterExtentPolicy,
    scene_origin_x: float | None = None,
    scene_origin_y: float | None = None,
) -> CoverageSnapshot | None:
    """Nearest-sample scene coverage into one joined-edge layer source."""
    scene_bounds = snapshot.bounds
    if scene_bounds is None:
        return None
    origin_x = float(scene_bounds.x) if scene_origin_x is None else scene_origin_x
    origin_y = float(scene_bounds.y) if scene_origin_y is None else scene_origin_y
    requested = _boundary_raster_bounds(mapping.source_boundary)
    destination = (
        requested if layer_bounds is None else requested.intersection(layer_bounds)
    )
    if destination is None:
        return None
    pixels = np.zeros((destination.height, destination.width), dtype=np.uint8)
    local_x = np.arange(destination.x, destination.right, dtype=np.float64) + 0.5
    for row, local_y in enumerate(
        np.arange(destination.y, destination.bottom, dtype=np.float64) + 0.5
    ):
        u, v, valid = inverse_bilinear_source_row(
            mapping.source_boundary, local_x, local_y
        )
        scene_x, scene_y = bilinear_coordinates(mapping.target_boundary, u, v)
        pixel_x = np.floor(scene_x - origin_x).astype(np.int64)
        pixel_y = np.floor(scene_y - origin_y).astype(np.int64)
        valid &= (
            (pixel_x >= 0)
            & (pixel_x < scene_bounds.width)
            & (pixel_y >= 0)
            & (pixel_y < scene_bounds.height)
        )
        if np.any(valid):
            pixels[row, valid] = snapshot.pixels[pixel_y[valid], pixel_x[valid]]
    return CoverageSnapshot(destination, extent_policy, pixels)


def _boundary_raster_bounds(
    boundary: tuple[QPointF, QPointF, QPointF, QPointF],
) -> RasterBounds:
    """Return integer storage enclosing one complete source boundary."""
    left = math.floor(min(point.x() for point in boundary))
    top = math.floor(min(point.y() for point in boundary))
    right = math.ceil(max(point.x() for point in boundary))
    bottom = math.ceil(max(point.y() for point in boundary))
    return RasterBounds(left, top, max(1, right - left), max(1, bottom - top))


__all__ = [
    "project_bilinear_coverage",
    "project_scene_coverage_to_bilinear_layer",
]
