#    QPane - High-performance PySide6 image viewer
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
"""Immutable raster-tile grids and physical-viewport sizing policy."""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QSize

AUTO_TILE_SIZE = "auto"
_AUTOMATIC_TILE_SIZES = (512, 1024, 2048, 4096)
_REFERENCE_VIEWPORT_AREA = 3840 * 2160
_REFERENCE_TARGET_VIEWPORT_TILES = 7.0
_MINIMUM_TARGET_VIEWPORT_TILES = 2.0
_HYSTERESIS_EDGE_RATIO = 1.12
_MINIMUM_CACHE_ENTRIES = 16


@dataclass(frozen=True, slots=True)
class RasterTileGrid:
    """Describe one source-product tile grid and its overlap geometry."""

    tile_size: int
    tile_overlap: int

    def __post_init__(self) -> None:
        """Reject grids that cannot advance through source pixels."""
        if isinstance(self.tile_size, bool) or self.tile_size <= 0:
            raise ValueError("tile_size must be a positive integer")
        if self.tile_overlap < 0 or self.tile_overlap >= self.tile_size:
            raise ValueError(
                "tile_overlap must be non-negative and smaller than tile_size"
            )

    @property
    def stride(self) -> int:
        """Return source pixels between adjacent tile origins."""
        return self.tile_size - self.tile_overlap

    @property
    def estimated_bytes(self) -> int:
        """Return the conservative ARGB32 byte footprint of one full tile."""
        return self.tile_size * self.tile_size * 4

    def dimensions_for(self, width: int, height: int) -> tuple[int, int]:
        """Return the grid dimensions required to cover a source product."""
        if width <= 0 or height <= 0:
            return 0, 0
        columns = max(
            1,
            (max(0, int(width) - self.tile_overlap) + self.stride - 1) // self.stride,
        )
        rows = max(
            1,
            (max(0, int(height) - self.tile_overlap) + self.stride - 1) // self.stride,
        )
        return columns, rows


def resolve_raster_tile_grid(
    tile_size: object,
    tile_overlap: object,
    physical_viewport_size: QSize,
    *,
    current_tile_size: int | None = None,
    cache_limit_bytes: int | None = None,
) -> RasterTileGrid:
    """Resolve a strict or automatic grid for one physical viewport.

    Args:
        tile_size: ``"auto"`` or a positive strict source-space tile edge.
        tile_overlap: Non-negative source pixels shared by neighboring tiles.
        physical_viewport_size: Current viewport extent in device pixels.
        current_tile_size: Current automatic bucket for hysteresis.
        cache_limit_bytes: Optional tile-cache allocation used to cap entries.

    Returns:
        The complete immutable grid selected for subsequent tile work.

    Raises:
        TypeError: If either setting has the wrong type.
        ValueError: If either setting cannot form a valid grid.
    """
    overlap = _strict_integer(tile_overlap, name="tile_overlap", minimum=0)
    if tile_size == AUTO_TILE_SIZE:
        if overlap >= _AUTOMATIC_TILE_SIZES[0]:
            raise ValueError(
                "tile_overlap must be smaller than every automatic tile size"
            )
        selected = _automatic_tile_size(
            physical_viewport_size,
            current_tile_size=current_tile_size,
            cache_limit_bytes=cache_limit_bytes,
        )
    else:
        selected = _strict_integer(tile_size, name="tile_size", minimum=1)
    return RasterTileGrid(selected, overlap)


def _automatic_tile_size(
    physical_viewport_size: QSize,
    *,
    current_tile_size: int | None,
    cache_limit_bytes: int | None,
) -> int:
    """Return a stable power-of-two bucket for one physical viewport."""
    width = max(1, int(physical_viewport_size.width()))
    height = max(1, int(physical_viewport_size.height()))
    viewport_area = width * height
    target_tiles = max(
        _MINIMUM_TARGET_VIEWPORT_TILES,
        _REFERENCE_TARGET_VIEWPORT_TILES
        * min(1.0, _REFERENCE_VIEWPORT_AREA / viewport_area),
    )
    target_edge = math.sqrt(viewport_area / target_tiles)
    candidate = _bucket_for_edge(target_edge)
    if current_tile_size in _AUTOMATIC_TILE_SIZES:
        candidate = _apply_hysteresis(
            candidate,
            current=int(current_tile_size),
            target_edge=target_edge,
        )
    return _cap_for_cache(candidate, cache_limit_bytes)


def _bucket_for_edge(target_edge: float) -> int:
    """Return the nearest supported bucket using geometric midpoints."""
    candidate = _AUTOMATIC_TILE_SIZES[0]
    for larger in _AUTOMATIC_TILE_SIZES[1:]:
        if target_edge < math.sqrt(candidate * larger):
            break
        candidate = larger
    return candidate


def _apply_hysteresis(candidate: int, *, current: int, target_edge: float) -> int:
    """Keep the current bucket until viewport growth clears a stable margin."""
    if candidate == current:
        return current
    midpoint = math.sqrt(candidate * current)
    if candidate > current:
        return (
            candidate if target_edge >= midpoint * _HYSTERESIS_EDGE_RATIO else current
        )
    return candidate if target_edge <= midpoint / _HYSTERESIS_EDGE_RATIO else current


def _cap_for_cache(candidate: int, cache_limit_bytes: int | None) -> int:
    """Keep at least a small working set admissible to the tile cache."""
    if cache_limit_bytes is None or cache_limit_bytes <= 0:
        return candidate
    maximum_entry_bytes = int(cache_limit_bytes) // _MINIMUM_CACHE_ENTRIES
    selected = candidate
    while (
        selected > _AUTOMATIC_TILE_SIZES[0]
        and selected * selected * 4 > maximum_entry_bytes
    ):
        selected //= 2
    return selected


def _strict_integer(value: object, *, name: str, minimum: int) -> int:
    """Return an exact integer setting without accepting bool or coercion."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < minimum:
        qualifier = "positive" if minimum == 1 else "non-negative"
        raise ValueError(f"{name} must be {qualifier}")
    return int(value)


__all__ = [
    "AUTO_TILE_SIZE",
    "RasterTileGrid",
    "resolve_raster_tile_grid",
]
