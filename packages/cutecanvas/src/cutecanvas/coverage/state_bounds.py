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
"""Derive exact visible bounds from detached coverage storage states."""

from __future__ import annotations

from cutecanvas.raster.content_bounds import occupied_channel_bounds
from cutecanvas.raster.sparse_grid import SparseRasterSnapshot
from qpane.sdk.scene import RasterBounds

from .content_bounds import occupied_coverage_bounds
from .surface import CoverageSnapshot, CoverageStateSnapshot


def coverage_state_content_bounds(
    state: CoverageStateSnapshot,
) -> RasterBounds | None:
    """Return exact nonzero layer-local bounds without materializing sparse gaps."""
    if isinstance(state, CoverageSnapshot):
        return occupied_coverage_bounds(state)
    if not isinstance(state, SparseRasterSnapshot):
        raise TypeError("state must be a coverage storage snapshot")
    content: RasterBounds | None = None
    for tile in state.tiles:
        tile_content = occupied_channel_bounds(tile.pixels)
        if tile_content is None:
            continue
        candidate = RasterBounds(
            tile.bounds.x + tile_content.x,
            tile.bounds.y + tile_content.y,
            tile_content.width,
            tile_content.height,
        )
        if state.bounds is not None:
            candidate = candidate.intersection(state.bounds)
            if candidate is None:
                continue
        content = candidate if content is None else content.united(candidate)
    return content


__all__ = ["coverage_state_content_bounds"]
