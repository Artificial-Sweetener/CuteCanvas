#    QPane + CuteCanvas - High-performance PySide6 rendering and editing
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
"""Tests for source-neutral selected-pixel extraction."""

from __future__ import annotations

import numpy as np
import pytest
from cutecanvas.coverage import CoverageSnapshot
from cutecanvas.scene.pixel_extraction import build_pixel_lift
from cutecanvas.scene.pixel_fragments import RasterPixelFormat
from cutecanvas.types import RasterExtentPolicy
from qpane.scene.raster import RasterBounds


@pytest.mark.parametrize(
    ("coverage_pixels", "expected_alpha"),
    (
        (np.full((2, 3), 255, dtype=np.uint8), np.zeros((2, 3), dtype=np.uint8)),
        (
            np.array([[255, 0, 255], [0, 255, 0]], dtype=np.uint8),
            np.array([[0, 200, 0], [200, 0, 200]], dtype=np.uint8),
        ),
        (
            np.array([[128, 64, 255], [0, 192, 32]], dtype=np.uint8),
            np.array([[100, 150, 0], [200, 49, 175]], dtype=np.uint8),
        ),
    ),
    ids=("full", "binary", "soft"),
)
def test_pixel_lift_fast_paths_preserve_exact_alpha_math(
    coverage_pixels: np.ndarray,
    expected_alpha: np.ndarray,
) -> None:
    """Full and binary acceleration must preserve exact soft-selection semantics."""
    bounds = RasterBounds(0, 0, 3, 2)
    source = np.full((2, 3, 4), 200, dtype=np.uint8)
    coverage = CoverageSnapshot(
        bounds,
        RasterExtentPolicy.FIXED,
        coverage_pixels,
    )

    lift = build_pixel_lift(
        source_pixels=source,
        coverage=coverage,
        pixel_format=RasterPixelFormat.PREMULTIPLIED_ARGB32,
        surface_bounds=bounds,
    )

    np.testing.assert_array_equal(
        lift.source_transition.after_pixels[:, :, 3],
        expected_alpha,
    )
    np.testing.assert_array_equal(lift.fragment.pixels, source)
    assert not lift.fragment.pixels.flags.writeable
