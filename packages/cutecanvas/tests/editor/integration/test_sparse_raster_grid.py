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
"""Adversarial contracts for sparse editable raster storage."""

import numpy as np

from cutecanvas.raster.sparse_grid import (
    SparseRasterGrid,
    reframe_sparse_raster_snapshot,
)
from cutecanvas.types import RasterExtentPolicy
from qpane.scene.raster import RasterBounds


def test_far_apart_writes_allocate_tiles_not_the_transparent_gap() -> None:
    """Unbounded content must scale with touched tiles rather than its envelope."""
    grid = SparseRasterGrid(channels=4, tile_size=64)
    first = np.full((8, 8, 4), 255, dtype=np.uint8)
    second = np.full((8, 8, 4), 127, dtype=np.uint8)

    grid.write(RasterBounds(-1_000_000, -1_000_000, 8, 8), first)
    grid.write(RasterBounds(1_000_000, 1_000_000, 8, 8), second)

    assert grid.tile_count == 2
    assert grid.allocated_bytes == 2 * 64 * 64 * 4
    np.testing.assert_array_equal(
        grid.read(RasterBounds(-1_000_000, -1_000_000, 8, 8)),
        first,
    )
    np.testing.assert_array_equal(
        grid.read(RasterBounds(1_000_000, 1_000_000, 8, 8)),
        second,
    )


def test_zero_write_prunes_tiles_and_fixed_crop_retains_only_intersection() -> None:
    """Cleared and clipped sparse content must release authoritative storage."""
    grid = SparseRasterGrid(channels=1, tile_size=64)
    pixels = np.full((96, 96), 255, dtype=np.uint8)
    grid.write(RasterBounds(-32, -32, 96, 96), pixels)
    assert grid.tile_count == 4

    grid.crop(RasterBounds(0, 0, 32, 32))

    assert grid.tile_count == 1
    assert grid.content_bounds() == RasterBounds(0, 0, 32, 32)
    grid.write(RasterBounds(0, 0, 32, 32), np.zeros((32, 32), dtype=np.uint8))
    assert grid.tile_count == 0
    assert grid.content_bounds() is None


def test_sparse_reframe_crops_edges_without_materializing_a_large_envelope() -> None:
    """Hard bounds must discard clipped pixels while retaining sparse gaps."""
    grid = SparseRasterGrid(channels=1, tile_size=64)
    pixels = np.full((32, 32), 255, dtype=np.uint8)
    grid.write(RasterBounds(-1_000_000, 0, 32, 32), pixels)
    grid.write(RasterBounds(1_000_000, 0, 32, 32), pixels)
    snapshot = grid.snapshot(
        RasterBounds(-1_000_000, 0, 2_000_032, 32),
        RasterExtentPolicy.UNBOUNDED,
    )

    expanded = reframe_sparse_raster_snapshot(
        snapshot,
        RasterBounds(-2_000_000, -100, 4_000_000, 200),
    )
    cropped = reframe_sparse_raster_snapshot(
        expanded,
        RasterBounds(999_984, 8, 32, 16),
    )

    assert expanded.retained_bytes == snapshot.retained_bytes
    assert len(expanded.tiles) == 2
    assert cropped.bounds == RasterBounds(999_984, 8, 32, 16)
    assert len(cropped.tiles) == 1
    assert cropped.retained_bytes == 64 * 64
    assert np.count_nonzero(cropped.tiles[0].pixels) == 16 * 16


def test_strided_read_samples_signed_tiles_without_materializing_the_envelope() -> None:
    """Display sampling must visit allocated tiles while preserving grid alignment."""
    grid = SparseRasterGrid(channels=1, tile_size=64)
    bounds = RasterBounds(-130, -66, 520, 260)
    first = RasterBounds(-129, -65, 5, 5)
    second = RasterBounds(255, 127, 5, 5)
    grid.write(first, np.full((5, 5), 73, dtype=np.uint8))
    grid.write(second, np.full((5, 5), 211, dtype=np.uint8))
    allocated_tiles = grid.tile_count

    sampled = grid.read_strided(bounds, 4)
    expected = grid.read(bounds)[::4, ::4]

    np.testing.assert_array_equal(sampled, expected)
    assert grid.tile_count == allocated_tiles
    assert sampled.shape == (65, 130)
