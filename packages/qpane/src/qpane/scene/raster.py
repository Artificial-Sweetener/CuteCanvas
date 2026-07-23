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
"""Source-local raster geometry shared by render domains."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRect, QSize

__all__ = ["RasterBounds"]


@dataclass(frozen=True, slots=True)
class RasterBounds:
    """Half-open integer bounds in a raster layer's local coordinate space."""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        """Validate positive raster storage dimensions."""
        if self.width <= 0 or self.height <= 0:
            raise ValueError("raster bounds dimensions must be positive")

    @classmethod
    def from_size(cls, size: QSize) -> RasterBounds:
        """Return origin-aligned bounds for a positive Qt size."""
        if size.width() <= 0 or size.height() <= 0:
            raise ValueError("raster size dimensions must be positive")
        return cls(0, 0, size.width(), size.height())

    @classmethod
    def from_qrect(cls, rect: QRect) -> RasterBounds:
        """Return validated bounds detached from ``rect``."""
        return cls(rect.x(), rect.y(), rect.width(), rect.height())

    @property
    def right(self) -> int:
        """Return the exclusive right coordinate."""
        return self.x + self.width

    @property
    def bottom(self) -> int:
        """Return the exclusive bottom coordinate."""
        return self.y + self.height

    def to_qrect(self) -> QRect:
        """Return a detached Qt rectangle with identical half-open extent."""
        return QRect(self.x, self.y, self.width, self.height)

    def united(self, other: RasterBounds) -> RasterBounds:
        """Return the smallest bounds containing both rectangles."""
        left = min(self.x, other.x)
        top = min(self.y, other.y)
        right = max(self.right, other.right)
        bottom = max(self.bottom, other.bottom)
        return RasterBounds(left, top, right - left, bottom - top)

    def intersection(self, other: RasterBounds) -> RasterBounds | None:
        """Return the positive-area overlap or ``None`` when disjoint."""
        left = max(self.x, other.x)
        top = max(self.y, other.y)
        right = min(self.right, other.right)
        bottom = min(self.bottom, other.bottom)
        if right <= left or bottom <= top:
            return None
        return RasterBounds(left, top, right - left, bottom - top)

    def contains(self, other: RasterBounds) -> bool:
        """Return whether ``other`` lies completely inside these bounds."""
        return (
            self.x <= other.x
            and self.y <= other.y
            and self.right >= other.right
            and self.bottom >= other.bottom
        )

    def translated(self, delta_x: int, delta_y: int) -> RasterBounds:
        """Return identical extents shifted in local pixel coordinates."""
        return RasterBounds(
            self.x + int(delta_x),
            self.y + int(delta_y),
            self.width,
            self.height,
        )
