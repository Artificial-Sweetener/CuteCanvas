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

"""Nearest-neighbor coverage resampling through finite affine patches."""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF
from qpane.sdk.scene import LayerTransform, PiecewiseLayerTransform, RasterBounds

from cutecanvas.coverage import CoverageSnapshot
from cutecanvas.types import RasterExtentPolicy


def project_piecewise_coverage(
    snapshot: CoverageSnapshot,
    mapping: PiecewiseLayerTransform,
    destination: RasterBounds,
) -> CoverageSnapshot:
    """Project source coverage into one explicit scene-space destination."""
    pixels = np.zeros((destination.height, destination.width), dtype=np.uint8)
    source_bounds = snapshot.bounds
    if source_bounds is None:
        return CoverageSnapshot(destination, RasterExtentPolicy.EXPAND_ON_WRITE, pixels)
    for patch in mapping.patches:
        inverse = patch.transform.inverted()
        if inverse is None:
            continue
        _sample_patch(
            output=pixels,
            output_bounds=destination,
            destination_triangle=patch.target,
            source_pixels=snapshot.pixels,
            source_bounds=source_bounds,
            destination_to_source=inverse,
        )
    return CoverageSnapshot(destination, RasterExtentPolicy.EXPAND_ON_WRITE, pixels)


def project_scene_coverage_to_piecewise_layer(
    snapshot: CoverageSnapshot,
    mapping: PiecewiseLayerTransform,
    *,
    layer_bounds: RasterBounds | None,
    extent_policy: RasterExtentPolicy,
) -> CoverageSnapshot | None:
    """Project scene coverage into the complete finite piecewise source cage."""
    scene_bounds = snapshot.bounds
    if scene_bounds is None:
        return None
    requested = _boundary_raster_bounds(mapping.source_boundary)
    destination = (
        requested if layer_bounds is None else requested.intersection(layer_bounds)
    )
    if destination is None:
        return None
    pixels = np.zeros((destination.height, destination.width), dtype=np.uint8)
    for patch in mapping.patches:
        _sample_patch(
            output=pixels,
            output_bounds=destination,
            destination_triangle=patch.source,
            source_pixels=snapshot.pixels,
            source_bounds=scene_bounds,
            destination_to_source=patch.transform,
        )
    return CoverageSnapshot(destination, extent_policy, pixels)


def _sample_patch(
    *,
    output: np.ndarray,
    output_bounds: RasterBounds,
    destination_triangle: tuple[QPointF, QPointF, QPointF],
    source_pixels: np.ndarray,
    source_bounds: RasterBounds,
    destination_to_source: LayerTransform,
) -> None:
    """Sample one affine triangle into its intersecting destination rows."""
    patch_bounds = _boundary_raster_bounds(destination_triangle).intersection(
        output_bounds
    )
    if patch_bounds is None:
        return
    x = np.arange(patch_bounds.x, patch_bounds.right, dtype=np.float64) + 0.5
    first = destination_triangle[0]
    edge_a = destination_triangle[1] - first
    edge_b = destination_triangle[2] - first
    determinant = edge_a.x() * edge_b.y() - edge_a.y() * edge_b.x()
    if abs(determinant) <= 1e-18:
        return
    for scene_y in (
        np.arange(patch_bounds.y, patch_bounds.bottom, dtype=np.float64) + 0.5
    ):
        relative_x = x - first.x()
        relative_y = scene_y - first.y()
        weight_a = (relative_x * edge_b.y() - relative_y * edge_b.x()) / determinant
        weight_b = (edge_a.x() * relative_y - edge_a.y() * relative_x) / determinant
        inside = (
            (weight_a >= -1e-9)
            & (weight_b >= -1e-9)
            & (weight_a + weight_b <= 1.0 + 1e-9)
        )
        if not np.any(inside):
            continue
        source_x = (
            destination_to_source.m11 * x
            + destination_to_source.m21 * scene_y
            + destination_to_source.dx
        )
        source_y = (
            destination_to_source.m12 * x
            + destination_to_source.m22 * scene_y
            + destination_to_source.dy
        )
        pixel_x = np.floor(source_x).astype(np.int64) - source_bounds.x
        pixel_y = np.floor(source_y).astype(np.int64) - source_bounds.y
        inside &= (
            (pixel_x >= 0)
            & (pixel_x < source_bounds.width)
            & (pixel_y >= 0)
            & (pixel_y < source_bounds.height)
        )
        if not np.any(inside):
            continue
        output_row = output[round(scene_y - 0.5) - output_bounds.y]
        output_columns = np.arange(
            patch_bounds.x - output_bounds.x,
            patch_bounds.right - output_bounds.x,
        )
        output_row[output_columns[inside]] = source_pixels[
            pixel_y[inside], pixel_x[inside]
        ]


def _boundary_raster_bounds(boundary: tuple[QPointF, ...]) -> RasterBounds:
    """Return integer bounds enclosing one finite polygon."""
    left = math.floor(min(point.x() for point in boundary))
    top = math.floor(min(point.y() for point in boundary))
    right = math.ceil(max(point.x() for point in boundary))
    bottom = math.ceil(max(point.y() for point in boundary))
    return RasterBounds(left, top, max(1, right - left), max(1, bottom - top))


__all__ = [
    "project_piecewise_coverage",
    "project_scene_coverage_to_piecewise_layer",
]
