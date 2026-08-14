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
"""Exact occupied bounds for immutable coverage snapshots."""

from __future__ import annotations

import numpy as np

from qpane.sdk.scene import RasterBounds

from .surface import CoverageSnapshot


def occupied_coverage_bounds(snapshot: CoverageSnapshot) -> RasterBounds | None:
    """Return the exact nonzero rectangle without enumerating every pixel."""
    bounds = snapshot.bounds
    pixels = snapshot.pixels
    if bounds is None or pixels.size == 0:
        return None
    occupied_rows = np.flatnonzero(np.any(pixels, axis=1))
    if occupied_rows.size == 0:
        return None
    occupied_columns = np.flatnonzero(np.any(pixels, axis=0))
    left = int(occupied_columns[0])
    top = int(occupied_rows[0])
    right = int(occupied_columns[-1]) + 1
    bottom = int(occupied_rows[-1]) + 1
    return RasterBounds(
        bounds.x + left,
        bounds.y + top,
        right - left,
        bottom - top,
    )
