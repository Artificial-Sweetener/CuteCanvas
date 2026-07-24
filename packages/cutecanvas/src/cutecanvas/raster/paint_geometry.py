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
"""Sparse tile geometry and soft constraints shared by raster brush operations."""

from __future__ import annotations

import math

import numpy as np
from qpane.sdk.scene import RasterBounds

from ..painting import BrushDab

PAINT_TILE_SIZE = 128
EXPANSION_MARGIN = 256


def expanded_surface_bounds(
    current: RasterBounds,
    requested: RasterBounds,
) -> RasterBounds:
    """Grow geometrically so long edge strokes avoid repeated reframing."""
    if current.contains(requested):
        return current
    horizontal_slack = max(EXPANSION_MARGIN, current.width // 2)
    vertical_slack = max(EXPANSION_MARGIN, current.height // 2)
    left = requested.x - horizontal_slack if requested.x < current.x else current.x
    top = requested.y - vertical_slack if requested.y < current.y else current.y
    right = (
        requested.right + horizontal_slack
        if requested.right > current.right
        else current.right
    )
    bottom = (
        requested.bottom + vertical_slack
        if requested.bottom > current.bottom
        else current.bottom
    )
    return RasterBounds(left, top, right - left, bottom - top)


def group_dabs_by_tile(
    dabs: tuple[BrushDab, ...],
    writable: RasterBounds,
) -> dict[RasterBounds, tuple[BrushDab, ...]]:
    """Spatially bin dabs so long diagonal strokes never allocate their AABB."""
    grouped: dict[RasterBounds, list[BrushDab]] = {}
    for dab in dabs:
        radius = dab.diameter / 2.0 + 1.0
        left = math.floor((dab.center[0] - radius) / PAINT_TILE_SIZE)
        top = math.floor((dab.center[1] - radius) / PAINT_TILE_SIZE)
        right = math.floor((dab.center[0] + radius) / PAINT_TILE_SIZE)
        bottom = math.floor((dab.center[1] + radius) / PAINT_TILE_SIZE)
        for tile_y in range(top, bottom + 1):
            for tile_x in range(left, right + 1):
                tile = RasterBounds(
                    tile_x * PAINT_TILE_SIZE,
                    tile_y * PAINT_TILE_SIZE,
                    PAINT_TILE_SIZE,
                    PAINT_TILE_SIZE,
                )
                if tile.intersection(writable) is not None:
                    grouped.setdefault(tile, []).append(dab)
    return {bounds: tuple(values) for bounds, values in grouped.items()}


def blend_constraint(
    before: np.ndarray,
    painted: np.ndarray,
    constraint: np.ndarray,
) -> np.ndarray:
    """Blend premultiplied paint through one soft selection constraint."""
    coverage = constraint.astype(np.uint16)[:, :, np.newaxis]
    inverse = 255 - coverage
    return (
        (
            before.astype(np.uint16) * inverse
            + painted.astype(np.uint16) * coverage
            + 127
        )
        // 255
    ).astype(np.uint8)
