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
"""Tests for cancellable paint-bucket coverage generation."""

from __future__ import annotations

import numpy as np
import pytest
from cutecanvas.coverage import CoverageSnapshot
from cutecanvas.fill import FillCancelledError, FloodFillEngine, FloodFillRequest
from cutecanvas.types import RasterExtentPolicy
from cutecanvas_test_support.harness.timing import interaction_clock
from qpane.scene.raster import RasterBounds


def test_contiguous_fill_does_not_cross_color_barrier() -> None:
    pixels = np.zeros((12, 20, 4), dtype=np.uint8)
    pixels[:, :, 3] = 255
    pixels[:, 9:11, :3] = 255

    result = FloodFillEngine().fill(
        FloodFillRequest(pixels, RasterBounds(0, 0, 20, 12), 2, 4, tolerance=0)
    )

    assert result is not None
    assert result.bounds == RasterBounds(0, 0, 9, 12)
    assert result.pixels.min() == 255


def test_noncontiguous_fill_selects_matching_islands() -> None:
    pixels = np.full((8, 12, 3), 200, dtype=np.uint8)
    pixels[1:3, 1:3] = 20
    pixels[5:7, 9:11] = 20

    result = FloodFillEngine().fill(
        FloodFillRequest(
            pixels,
            RasterBounds(0, 0, 12, 8),
            1,
            1,
            tolerance=0,
            contiguous=False,
            antialias=False,
        )
    )

    assert result is not None
    assert result.bounds == RasterBounds(1, 1, 10, 6)
    assert np.count_nonzero(result.pixels) == 8


def test_fill_honors_soft_selection_constraint() -> None:
    pixels = np.zeros((6, 6, 4), dtype=np.uint8)
    constraint_pixels = np.zeros((4, 4), dtype=np.uint8)
    constraint_pixels[:, :] = 128
    constraint = CoverageSnapshot(
        RasterBounds(1, 1, 4, 4),
        RasterExtentPolicy.EXPAND_ON_WRITE,
        constraint_pixels,
    )

    result = FloodFillEngine().fill(
        FloodFillRequest(
            pixels,
            RasterBounds(0, 0, 6, 6),
            2,
            2,
            tolerance=0,
            antialias=False,
            constraint=constraint,
        )
    )

    assert result is not None
    assert result.bounds == RasterBounds(1, 1, 4, 4)
    assert result.pixels.min() == 128


def test_fill_cancels_without_returning_partial_coverage() -> None:
    pixels = np.zeros((1024, 1024, 4), dtype=np.uint8)
    polls = 0

    def cancelled() -> bool:
        """Cancel after the engine has yielded to its cooperative check."""
        nonlocal polls
        polls += 1
        return polls >= 1

    with pytest.raises(FillCancelledError):
        FloodFillEngine().fill(
            FloodFillRequest(
                pixels,
                RasterBounds(0, 0, 1024, 1024),
                512,
                512,
                tolerance=0,
            ),
            cancelled=cancelled,
        )


def test_uniform_8k_fill_stays_within_abuse_latency_and_memory_shape() -> None:
    """A worst-area fill should remain interactive off-thread without huge indices."""
    size = 8192
    pixels = np.zeros((size, size), dtype=np.uint8)

    started = interaction_clock()
    result = FloodFillEngine().fill(
        FloodFillRequest(
            pixels,
            RasterBounds(0, 0, size, size),
            size // 2,
            size // 2,
            tolerance=0,
            antialias=False,
        )
    )
    elapsed = interaction_clock() - started

    assert result is not None
    assert result.bounds == RasterBounds(0, 0, size, size)
    assert elapsed < 3.0
