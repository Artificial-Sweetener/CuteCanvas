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
"""Allocation-bounded occupied-bounds queries for canonical raster channels."""

from __future__ import annotations

import numpy as np
from qpane.sdk.scene import RasterBounds


def occupied_channel_bounds(pixels: np.ndarray) -> RasterBounds | None:
    """Return exact nonzero bounds for one two-dimensional pixel channel."""
    channel = np.asarray(pixels)
    if channel.ndim != 2:
        raise ValueError("occupied bounds require a two-dimensional channel")
    height, width = channel.shape
    if height == 0 or width == 0:
        return None
    if np.all(channel):
        return RasterBounds(0, 0, width, height)
    if not np.any(channel):
        return None
    occupied_rows = np.flatnonzero(np.any(channel, axis=1))
    top = int(occupied_rows[0])
    bottom = int(occupied_rows[-1]) + 1
    occupied_columns = np.flatnonzero(np.any(channel[top:bottom], axis=0))
    left = int(occupied_columns[0])
    right = int(occupied_columns[-1]) + 1
    return RasterBounds(left, top, right - left, bottom - top)
