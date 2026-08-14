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
"""Copy-on-write raster reads preserving a stroke's pre-edit source revision."""

from __future__ import annotations

import math

import numpy as np

from qpane.sdk.scene import RasterBounds

from .color_surface import ColorRasterSurface

_REVISION_TILE_SIZE = 128
_FRACTION_SCALE = 256


class RasterRevisionReader:
    """Read pre-stroke pixels while retaining only destination tiles that change."""

    def __init__(self, surface: ColorRasterSurface) -> None:
        """Capture source identity without copying its complete logical extent."""
        self._surface = surface
        self._initial_revision = surface.revisions()
        self._preserved: dict[RasterBounds, np.ndarray] = {}

    @property
    def retained_bytes(self) -> int:
        """Return exact bytes retained to preserve overwritten source tiles."""
        return sum(pixels.nbytes for pixels in self._preserved.values())

    def preserve(self, bounds: RasterBounds) -> None:
        """Capture canonical pre-stroke tiles before destination pixels mutate."""
        for tile in _tiles_covering(bounds, _REVISION_TILE_SIZE):
            self._preserved.setdefault(tile, self._surface.capture_region(tile))

    def read(self, bounds: RasterBounds) -> np.ndarray:
        """Return exact pre-stroke pixels for an arbitrary local region."""
        pixels = self._surface.capture_region(bounds)
        for tile, before in self._preserved.items():
            overlap = tile.intersection(bounds)
            if overlap is None:
                continue
            source_x = overlap.x - tile.x
            source_y = overlap.y - tile.y
            target_x = overlap.x - bounds.x
            target_y = overlap.y - bounds.y
            pixels[
                target_y : target_y + overlap.height,
                target_x : target_x + overlap.width,
            ] = before[
                source_y : source_y + overlap.height,
                source_x : source_x + overlap.width,
            ]
        return pixels

    def sample_translated(
        self,
        destination: RasterBounds,
        offset: tuple[float, float],
    ) -> np.ndarray:
        """Sample translated premultiplied pixels with fixed-point bilinear filtering."""
        offset_x, offset_y = map(float, offset)
        integer_x = math.floor(offset_x)
        integer_y = math.floor(offset_y)
        fraction_x = round((offset_x - integer_x) * _FRACTION_SCALE)
        fraction_y = round((offset_y - integer_y) * _FRACTION_SCALE)
        if fraction_x == _FRACTION_SCALE:
            integer_x += 1
            fraction_x = 0
        if fraction_y == _FRACTION_SCALE:
            integer_y += 1
            fraction_y = 0
        source = RasterBounds(
            destination.x + integer_x,
            destination.y + integer_y,
            destination.width + (1 if fraction_x else 0),
            destination.height + (1 if fraction_y else 0),
        )
        pixels = self.read(source)
        if not fraction_x and not fraction_y:
            return pixels
        left = pixels[:, : destination.width].astype(np.uint32)
        if fraction_x:
            right = pixels[:, 1 : destination.width + 1].astype(np.uint32)
            horizontal = (
                left * (_FRACTION_SCALE - fraction_x)
                + right * fraction_x
                + _FRACTION_SCALE // 2
            ) // _FRACTION_SCALE
        else:
            horizontal = left
        top = horizontal[: destination.height]
        if fraction_y:
            bottom = horizontal[1 : destination.height + 1]
            sampled = (
                top * (_FRACTION_SCALE - fraction_y)
                + bottom * fraction_y
                + _FRACTION_SCALE // 2
            ) // _FRACTION_SCALE
        else:
            sampled = top
        return np.ascontiguousarray(sampled.astype(np.uint8))


def _tiles_covering(
    bounds: RasterBounds,
    tile_size: int,
) -> tuple[RasterBounds, ...]:
    """Return canonical signed tiles intersecting ``bounds``."""
    left = bounds.x // tile_size
    top = bounds.y // tile_size
    right = (bounds.right - 1) // tile_size
    bottom = (bounds.bottom - 1) // tile_size
    return tuple(
        RasterBounds(
            tile_x * tile_size,
            tile_y * tile_size,
            tile_size,
            tile_size,
        )
        for tile_y in range(top, bottom + 1)
        for tile_x in range(left, right + 1)
    )
