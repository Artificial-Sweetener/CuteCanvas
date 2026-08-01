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
"""Compare immutable dense and sparse coverage snapshots semantically."""

from __future__ import annotations

import numpy as np

from ..raster.sparse_grid import SparseRasterSnapshot
from .surface import CoverageSnapshot, CoverageStateSnapshot


def coverage_state_snapshots_equal(
    left: CoverageStateSnapshot,
    right: CoverageStateSnapshot,
) -> bool:
    """Return whether complete coverage surface states contain equal pixels."""
    if left is right:
        return True
    if isinstance(left, SparseRasterSnapshot) or isinstance(
        right, SparseRasterSnapshot
    ):
        if not isinstance(left, SparseRasterSnapshot) or not isinstance(
            right, SparseRasterSnapshot
        ):
            return False
        return (
            left.bounds == right.bounds
            and left.extent_policy is right.extent_policy
            and left.channels == right.channels
            and left.tile_size == right.tile_size
            and len(left.tiles) == len(right.tiles)
            and all(
                left_tile.bounds == right_tile.bounds
                and np.array_equal(left_tile.pixels, right_tile.pixels)
                for left_tile, right_tile in zip(left.tiles, right.tiles, strict=True)
            )
        )
    if not isinstance(left, CoverageSnapshot) or not isinstance(
        right, CoverageSnapshot
    ):
        return False
    return (
        left.bounds == right.bounds
        and left.extent_policy is right.extent_policy
        and np.array_equal(left.pixels, right.pixels)
    )


__all__ = ["coverage_state_snapshots_equal"]
