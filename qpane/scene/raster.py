#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Raster-layer geometry and extent policy values shared across domains."""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRect, QRectF, QSize

from ..types import RasterExtentPolicy
from .model import LayerPlacement

__all__ = ["LayerTransform", "RasterBounds", "RasterExtentPolicy"]


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


@dataclass(frozen=True, slots=True)
class LayerTransform:
    """Map raster-local coordinates into scene space without owning an extent."""

    scale_x: float = 1.0
    scale_y: float = 1.0
    translate_x: float = 0.0
    translate_y: float = 0.0

    def __post_init__(self) -> None:
        """Validate finite non-negative axis-aligned transform values."""
        values = (self.scale_x, self.scale_y, self.translate_x, self.translate_y)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("layer transform values must be finite")
        if self.scale_x < 0.0 or self.scale_y < 0.0:
            raise ValueError("layer transform scales must be non-negative")

    @classmethod
    def from_placement(
        cls,
        bounds: RasterBounds,
        placement: LayerPlacement,
    ) -> LayerTransform:
        """Return the transform mapping ``bounds`` exactly onto ``placement``."""
        scale_x = placement.width / bounds.width
        scale_y = placement.height / bounds.height
        return cls(
            scale_x=scale_x,
            scale_y=scale_y,
            translate_x=placement.x - bounds.x * scale_x,
            translate_y=placement.y - bounds.y * scale_y,
        )

    def map_point(self, point: QPointF) -> QPointF:
        """Map one raster-local point into scene coordinates."""
        return QPointF(
            point.x() * self.scale_x + self.translate_x,
            point.y() * self.scale_y + self.translate_y,
        )

    def map_bounds(self, bounds: RasterBounds) -> LayerPlacement:
        """Return the scene placement occupied by ``bounds``."""
        origin = self.map_point(QPointF(float(bounds.x), float(bounds.y)))
        return LayerPlacement(
            x=origin.x(),
            y=origin.y(),
            width=bounds.width * self.scale_x,
            height=bounds.height * self.scale_y,
        )

    def translated(self, delta_x: float, delta_y: float) -> LayerTransform:
        """Return a scene-space translation without changing raster scale."""
        return LayerTransform(
            scale_x=self.scale_x,
            scale_y=self.scale_y,
            translate_x=self.translate_x + delta_x,
            translate_y=self.translate_y + delta_y,
        )

    def inverse_map(self, point: QPointF) -> QPointF | None:
        """Map a scene point into raster-local space when invertible."""
        if self.scale_x == 0.0 or self.scale_y == 0.0:
            return None
        return QPointF(
            (point.x() - self.translate_x) / self.scale_x,
            (point.y() - self.translate_y) / self.scale_y,
        )

    def map_rect(self, rect: QRect) -> QRectF:
        """Map an arbitrary integer local rectangle into scene coordinates."""
        origin = self.map_point(QPointF(float(rect.x()), float(rect.y())))
        return QRectF(
            origin.x(),
            origin.y(),
            rect.width() * self.scale_x,
            rect.height() * self.scale_y,
        )
