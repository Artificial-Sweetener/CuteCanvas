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
"""Authoritative affine geometry for composition layer instances."""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRect, QRectF
from PySide6.QtGui import QTransform

from .model import LayerPlacement
from .raster import RasterBounds


@dataclass(frozen=True, slots=True)
class LayerTransform:
    """Map source-local coordinates into scene space with one affine value."""

    m11: float = 1.0
    m12: float = 0.0
    m21: float = 0.0
    m22: float = 1.0
    dx: float = 0.0
    dy: float = 0.0

    def __post_init__(self) -> None:
        """Reject non-finite coefficients that cannot enter geometry or caches."""
        if not all(
            math.isfinite(value)
            for value in (self.m11, self.m12, self.m21, self.m22, self.dx, self.dy)
        ):
            raise ValueError("layer transform coefficients must be finite")

    @classmethod
    def from_placement(
        cls,
        bounds: RasterBounds,
        placement: LayerPlacement,
    ) -> LayerTransform:
        """Return the axis-aligned transform mapping bounds onto placement."""
        scale_x = placement.width / bounds.width
        scale_y = placement.height / bounds.height
        return cls(
            m11=scale_x,
            m22=scale_y,
            dx=placement.x - bounds.x * scale_x,
            dy=placement.y - bounds.y * scale_y,
        )

    @classmethod
    def from_qtransform(cls, transform: QTransform) -> LayerTransform:
        """Detach one affine Qt transform into the domain value."""
        if not transform.isAffine():
            raise ValueError("layer transforms must be affine")
        return cls(
            m11=transform.m11(),
            m12=transform.m12(),
            m21=transform.m21(),
            m22=transform.m22(),
            dx=transform.dx(),
            dy=transform.dy(),
        )

    @property
    def determinant(self) -> float:
        """Return the determinant of the linear transform component."""
        return self.m11 * self.m22 - self.m12 * self.m21

    @property
    def is_invertible(self) -> bool:
        """Return whether inverse mapping is numerically usable."""
        magnitude = max(abs(self.m11), abs(self.m12), abs(self.m21), abs(self.m22), 1.0)
        return abs(self.determinant) > 1e-12 * magnitude * magnitude

    @property
    def is_axis_aligned(self) -> bool:
        """Return whether local axes remain parallel to scene axes."""
        return self.m12 == 0.0 and self.m21 == 0.0

    def to_qtransform(self) -> QTransform:
        """Return a detached Qt value with identical affine coefficients."""
        return QTransform(
            self.m11,
            self.m12,
            self.m21,
            self.m22,
            self.dx,
            self.dy,
        )

    def map_point(self, point: QPointF) -> QPointF:
        """Map one source-local point into scene coordinates."""
        return QPointF(
            self.m11 * point.x() + self.m21 * point.y() + self.dx,
            self.m12 * point.x() + self.m22 * point.y() + self.dy,
        )

    def map_vector(self, vector: QPointF) -> QPointF:
        """Map one displacement without applying translation."""
        return QPointF(
            self.m11 * vector.x() + self.m21 * vector.y(),
            self.m12 * vector.x() + self.m22 * vector.y(),
        )

    def inverse_map(self, point: QPointF) -> QPointF | None:
        """Map a scene point into source-local space when invertible."""
        if not self.is_invertible:
            return None
        translated_x = point.x() - self.dx
        translated_y = point.y() - self.dy
        determinant = self.determinant
        return QPointF(
            (self.m22 * translated_x - self.m21 * translated_y) / determinant,
            (-self.m12 * translated_x + self.m11 * translated_y) / determinant,
        )

    def inverse_map_vector(self, vector: QPointF) -> QPointF | None:
        """Map a scene displacement into source-local space when invertible."""
        if not self.is_invertible:
            return None
        determinant = self.determinant
        return QPointF(
            (self.m22 * vector.x() - self.m21 * vector.y()) / determinant,
            (-self.m12 * vector.x() + self.m11 * vector.y()) / determinant,
        )

    def inverted(self) -> LayerTransform | None:
        """Return the scene-to-local affine value when numerically usable."""
        if not self.is_invertible:
            return None
        determinant = self.determinant
        inverse_m11 = self.m22 / determinant
        inverse_m12 = -self.m12 / determinant
        inverse_m21 = -self.m21 / determinant
        inverse_m22 = self.m11 / determinant
        return LayerTransform(
            m11=inverse_m11,
            m12=inverse_m12,
            m21=inverse_m21,
            m22=inverse_m22,
            dx=-(inverse_m11 * self.dx + inverse_m21 * self.dy),
            dy=-(inverse_m12 * self.dx + inverse_m22 * self.dy),
        )

    def followed_by(self, next_transform: LayerTransform) -> LayerTransform:
        """Return the explicit composition ``next_transform(self(point))``."""
        return LayerTransform(
            m11=next_transform.m11 * self.m11 + next_transform.m21 * self.m12,
            m12=next_transform.m12 * self.m11 + next_transform.m22 * self.m12,
            m21=next_transform.m11 * self.m21 + next_transform.m21 * self.m22,
            m22=next_transform.m12 * self.m21 + next_transform.m22 * self.m22,
            dx=next_transform.m11 * self.dx
            + next_transform.m21 * self.dy
            + next_transform.dx,
            dy=next_transform.m12 * self.dx
            + next_transform.m22 * self.dy
            + next_transform.dy,
        )

    def map_bounds(self, bounds: RasterBounds) -> LayerPlacement:
        """Return the conservative scene-space bound of local raster bounds."""
        mapped = self._mapped_corners(
            float(bounds.x),
            float(bounds.y),
            float(bounds.right),
            float(bounds.bottom),
        )
        left = min(point.x() for point in mapped)
        top = min(point.y() for point in mapped)
        right = max(point.x() for point in mapped)
        bottom = max(point.y() for point in mapped)
        return LayerPlacement(left, top, right - left, bottom - top)

    def map_rect(self, rect: QRect | QRectF) -> QRectF:
        """Return the conservative scene-space bound of a local Qt rectangle."""
        left = float(rect.x())
        top = float(rect.y())
        right = left + float(rect.width())
        bottom = top + float(rect.height())
        mapped = self._mapped_corners(left, top, right, bottom)
        mapped_left = min(point.x() for point in mapped)
        mapped_top = min(point.y() for point in mapped)
        mapped_right = max(point.x() for point in mapped)
        mapped_bottom = max(point.y() for point in mapped)
        return QRectF(
            mapped_left,
            mapped_top,
            mapped_right - mapped_left,
            mapped_bottom - mapped_top,
        )

    def translated(self, delta_x: float, delta_y: float) -> LayerTransform:
        """Return a scene-space translation without changing local geometry."""
        return LayerTransform(
            self.m11,
            self.m12,
            self.m21,
            self.m22,
            self.dx + delta_x,
            self.dy + delta_y,
        )

    def _mapped_corners(
        self,
        left: float,
        top: float,
        right: float,
        bottom: float,
    ) -> tuple[QPointF, QPointF, QPointF, QPointF]:
        """Map four rectangle corners without constructing mutable Qt paths."""
        return (
            self.map_point(QPointF(left, top)),
            self.map_point(QPointF(right, top)),
            self.map_point(QPointF(right, bottom)),
            self.map_point(QPointF(left, bottom)),
        )
