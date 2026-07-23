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
"""Exact source-neutral extraction of selected raster fragments."""

from __future__ import annotations

import numpy as np
from qpane.sdk.scene import RasterBounds

from ..coverage import CoverageSnapshot
from .pixel_fragments import RasterPixelFormat, RasterPixelFragment, RasterPixelLift
from .pixel_transitions import RasterPixelTransition


def build_pixel_lift(
    *,
    source_pixels: np.ndarray,
    coverage: CoverageSnapshot,
    pixel_format: RasterPixelFormat,
    surface_bounds: RasterBounds,
) -> RasterPixelLift:
    """Build immutable payload and exact cleared-source transition."""
    bounds = coverage.bounds
    if bounds is None:
        raise ValueError("pixel lift requires bounded selection coverage")
    before = np.ascontiguousarray(source_pixels, dtype=np.uint8)
    minimum_coverage = int(coverage.pixels.min())
    maximum_coverage = int(coverage.pixels.max())
    if minimum_coverage == 255:
        after = np.zeros_like(before)
    elif (
        minimum_coverage == 0
        and maximum_coverage == 255
        and not np.any((coverage.pixels != 0) & (coverage.pixels != 255))
    ):
        after = np.array(before, copy=True, order="C")
        after[coverage.pixels != 0] = 0
    else:
        selection = coverage.pixels.astype(np.uint16)
        if before.ndim == 3:
            selection = selection[:, :, np.newaxis]
        after = np.ascontiguousarray(
            ((before.astype(np.uint16) * (255 - selection) + 127) // 255).astype(
                np.uint8
            )
        )
    fragment = RasterPixelFragment._adopt_detached(
        bounds,
        pixel_format,
        before,
        coverage,
    )
    transition = RasterPixelTransition._adopt_detached(
        bounds,
        surface_bounds,
        surface_bounds,
        before,
        after,
    )
    return RasterPixelLift(fragment, transition)
