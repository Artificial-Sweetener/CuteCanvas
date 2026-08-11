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

_PROJECTION_WORKING_SET_BYTES = 96 * 1024 * 1024
_PROJECTION_FLOAT_ARRAY_COUNT = 7
_MAXIMUM_PROJECTION_ROWS = 2048


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
    scene_x = (
        canvas_x + np.arange(target_left, target_right, dtype=np.float64)[None, :] + 0.5
    )
    relative_x = scene_x - apex.x()
    source = mapping.source_boundary
    row_chunk = _projection_row_chunk(target_right - target_left)
    for chunk_top in range(target_top, target_bottom, row_chunk):
        chunk_bottom = min(target_bottom, chunk_top + row_chunk)
        chunk_shape = (chunk_bottom - chunk_top, target_right - target_left)
        scene_y = (
            canvas_y
            + np.arange(chunk_top, chunk_bottom, dtype=np.float64)[:, None]
            + 0.5
        )
        relative_y = scene_y - apex.y()
        working = np.empty(chunk_shape, dtype=np.float64)
        v = np.empty_like(working)
        np.multiply(relative_x, right.y() - left.y(), out=v)
        np.multiply(relative_y, left.x() - right.x(), out=working)
        v += working
        v /= determinant
        u = np.empty_like(working)
        np.multiply(relative_y, left.x(), out=u)
        np.multiply(relative_x, left.y(), out=working)
        u -= working
        u /= determinant
        valid = (v <= 1.0) & (v > 1e-12) & (u >= 0.0)
        np.subtract(v, u, out=working)
        valid &= working >= 0.0
        if not np.any(valid):
            continue
        np.divide(u, v, out=u, where=valid)
        u[~valid] = 0.0
        np.clip(u, 0.0, 1.0, out=u)
        source_x = _bilinear_coordinate(
            tuple(point.x() for point in source),
            u,
            v,
            working,
        )
        pixel_x = np.floor(source_x).astype(np.int64) - bounds.x
        del source_x
        source_y = _bilinear_coordinate(
            tuple(point.y() for point in source),
            u,
            v,
            working,
        )
        pixel_y = np.floor(source_y).astype(np.int64) - bounds.y
        valid &= (
            (pixel_x >= 0)
            & (pixel_x < bounds.width)
            & (pixel_y >= 0)
            & (pixel_y < bounds.height)
        )
        if np.any(valid):
            destination = result[chunk_top:chunk_bottom, target_left:target_right]
            destination[valid] = snapshot.pixels[pixel_y[valid], pixel_x[valid]]
    return result


def _bilinear_coordinate(
    values: tuple[float, float, float, float],
    u: np.ndarray,
    v: np.ndarray,
    working: np.ndarray,
) -> np.ndarray:
    """Evaluate one bilinear coordinate while reusing bounded scratch storage."""
    first, second, third, fourth = values
    result = np.empty_like(u)
    np.multiply(u, second - first, out=result)
    result += first
    np.multiply(v, fourth - first, out=working)
    result += working
    np.multiply(u, v, out=working)
    working *= first - second - fourth + third
    result += working
    return result


def _projection_row_chunk(width: int) -> int:
    """Choose a wide vector batch without exceeding the working-set target."""
    row_bytes = max(1, width) * np.dtype(np.float64).itemsize
    estimated_row_bytes = row_bytes * _PROJECTION_FLOAT_ARRAY_COUNT
    return max(
        1,
        min(
            _MAXIMUM_PROJECTION_ROWS,
            _PROJECTION_WORKING_SET_BYTES // estimated_row_bytes,
        ),
    )


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
