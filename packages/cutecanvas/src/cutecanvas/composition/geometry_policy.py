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
"""Immutable host policy for layer manipulation geometry."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QPointF
from qpane.sdk.scene import RasterBounds


class LayerGeometryMode(str, Enum):
    """Select the source-local bounds used by editor manipulation."""

    CONTENT = "content"
    STORAGE = "storage"
    SOURCE = "source"
    CLIP = "clip"
    AUTHORED = "authored"
    BOUNDARY = "boundary"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class LayerGeometryPolicy:
    """Configure manipulation geometry independently from render clipping."""

    mode: LayerGeometryMode = LayerGeometryMode.CONTENT
    custom_bounds: RasterBounds | None = None
    custom_boundary: tuple[tuple[float, float], ...] | None = None

    def __post_init__(self) -> None:
        """Validate custom geometry only for the custom policy mode."""
        mode = LayerGeometryMode(self.mode)
        if mode is LayerGeometryMode.CUSTOM and self.custom_bounds is None:
            raise ValueError("custom layer geometry requires custom_bounds")
        if mode is not LayerGeometryMode.CUSTOM and self.custom_bounds is not None:
            raise ValueError("custom_bounds are valid only for custom geometry")
        if mode is LayerGeometryMode.BOUNDARY:
            if (
                self.custom_boundary is None
                or not 3 <= len(self.custom_boundary) <= 128
            ):
                raise ValueError("boundary layer geometry requires 3 to 128 points")
        elif self.custom_boundary is not None:
            raise ValueError("custom_boundary is valid only for boundary geometry")
        boundary = (
            None
            if self.custom_boundary is None
            else tuple(_validated_coordinates(point) for point in self.custom_boundary)
        )
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "custom_boundary", boundary)

    def boundary_points(self) -> tuple[QPointF, ...]:
        """Return detached Qt points for explicit polygon geometry."""
        return tuple(QPointF(x, y) for x, y in self.custom_boundary or ())


def _validated_coordinates(point: tuple[float, float]) -> tuple[float, float]:
    """Return one finite immutable coordinate pair."""
    if len(point) != 2:
        raise ValueError("boundary points require exactly two coordinates")
    coordinates = float(point[0]), float(point[1])
    if not all(math.isfinite(value) for value in coordinates):
        raise ValueError("boundary coordinates must be finite")
    return coordinates
