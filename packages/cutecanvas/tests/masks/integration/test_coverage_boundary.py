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

"""Raster coverage boundary extraction contracts."""

from __future__ import annotations

import numpy as np
from cutecanvas import RasterExtentPolicy
from cutecanvas.coverage import CoverageSnapshot
from cutecanvas.coverage.boundary import (
    coverage_convex_boundary,
    sparse_coverage_convex_boundary,
)
from cutecanvas.raster.sparse_grid import SparseRasterGrid
from qpane.sdk.scene import RasterBounds


def test_diagonal_raster_coverage_produces_oriented_boundary_edges() -> None:
    """Legacy raster masks retain diagonal candidates instead of a bounds box."""
    pixels = np.zeros((20, 20), dtype=np.uint8)
    for row in range(20):
        pixels[row, : row + 1] = 255
    snapshot = CoverageSnapshot(
        RasterBounds(30, 40, 20, 20),
        RasterExtentPolicy.EXPAND_ON_WRITE,
        pixels,
    )

    boundary = coverage_convex_boundary(snapshot)

    coordinates = {(point.x(), point.y()) for point in boundary}
    assert (31.0, 40.0) in coordinates
    assert (50.0, 60.0) in coordinates
    assert any(
        start.x() != end.x() and start.y() != end.y()
        for start, end in zip(boundary, (*boundary[1:], boundary[0]), strict=True)
    )


def test_sparse_boundary_matches_dense_boundary_without_gap_allocation() -> None:
    """Sparse masks must produce identical edges without densifying their extent."""
    pixels = np.zeros((20, 20), dtype=np.uint8)
    for row in range(20):
        pixels[row, : row + 1] = 255
    bounds = RasterBounds(30, 40, 20, 20)
    dense = CoverageSnapshot(
        bounds,
        RasterExtentPolicy.EXPAND_ON_WRITE,
        pixels,
    )
    grid = SparseRasterGrid(channels=1, tile_size=32)
    grid.replace(bounds, pixels)

    sparse_boundary = sparse_coverage_convex_boundary(
        grid.snapshot(bounds, RasterExtentPolicy.EXPAND_ON_WRITE)
    )

    assert sparse_boundary == coverage_convex_boundary(dense)
