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
"""Create one checked, detached raster tile product."""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtGui import QImage

from ..execution import CancellationToken
from ..scene.identity import SceneLayerTileKey
from .storage_allocation import require_image


@dataclass(slots=True, frozen=True)
class Tile:
    """Carry one detached tile and its exact native byte footprint."""

    key: SceneLayerTileKey
    image: QImage
    size_bytes: int = field(init=False)

    def __post_init__(self) -> None:
        """Capture the native byte footprint after validating the product."""
        if self.image.isNull():
            raise ValueError("tile image must not be null")
        object.__setattr__(self, "size_bytes", self.image.sizeInBytes())


def generate_tile(
    key: SceneLayerTileKey,
    source_image: QImage,
    cancellation: CancellationToken,
) -> Tile:
    """Crop one detached tile product cooperatively."""
    cancellation.raise_if_cancelled()
    stride = key.tile_size - key.tile_overlap
    x = key.col * stride
    y = key.row * stride
    cropped_image = require_image(
        source_image.copy(x, y, key.tile_size, key.tile_size),
        "tile crop",
    )
    cancellation.raise_if_cancelled()
    return Tile(key=key, image=cropped_image)


__all__ = ["Tile", "generate_tile"]
