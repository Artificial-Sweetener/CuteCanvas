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

"""Immutable projective geometry for composition layer instances."""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRect, QRectF
from PySide6.QtGui import QPolygonF, QTransform

from .affine import LayerTransform
from .model import LayerPlacement
from .raster import RasterBounds

_HORIZON_EPSILON = 1e-12


@dataclass(frozen=True, slots=True)
class ProjectiveLayerTransform:
    """Map source-local points into scene space with one homography."""

    m11: float = 1.0
    m12: float = 0.0
    m13: float = 0.0
    m21: float = 0.0
    m22: float = 1.0
    m23: float = 0.0
    dx: float = 0.0
    dy: float = 0.0
    m33: float = 1.0

    def __post_init__(self) -> None:
        """Reject coefficients that cannot enter geometry or cache identity."""
        if not all(math.isfinite(value) for value in self.coefficients):
            raise ValueError("projective layer transform coefficients must be finite")

    @property
    def coefficients(self) -> tuple[float, ...]:
        """Return all coefficients in Qt matrix order."""
        return (
            self.m11,
            self.m12,
            self.m13,
            self.m21,
            self.m22,
            self.m23,
            self.dx,
            self.dy,
            self.m33,
        )

    @classmethod
    def from_qtransform(cls, transform: QTransform) -> ProjectiveLayerTransform:
        """Detach all nine coefficients from one Qt transform."""
        if not isinstance(transform, QTransform):
            raise TypeError("transform must be a QTransform")
        return cls(
            transform.m11(),
            transform.m12(),
            transform.m13(),
            transform.m21(),
            transform.m22(),
            transform.m23(),
            transform.m31(),
            transform.m32(),
            transform.m33(),
        )

    @classmethod
    def from_quadrilaterals(
        cls,
        source: tuple[QPointF, QPointF, QPointF, QPointF],
        target: tuple[QPointF, QPointF, QPointF, QPointF],
    ) -> ProjectiveLayerTransform:
        """Solve the homography mapping four ordered source points to targets."""
        source_points = _finite_quad(source, name="source")
        target_points = _finite_quad(target, name="target")
        transform = QTransform.quadToQuad(
            QPolygonF(source_points),
            QPolygonF(target_points),
        )
        if transform is None:
            raise ValueError("quadrilaterals do not define a projective mapping")
        return cls.from_qtransform(transform)

    @property
    def is_invertible(self) -> bool:
        """Return whether Qt can produce a finite inverse matrix."""
        return bool(self.to_qtransform().isInvertible())

    def to_qtransform(self) -> QTransform:
        """Return a detached Qt value with identical coefficients."""
        return QTransform(*self.coefficients)

    def map_point(self, point: QPointF) -> QPointF:
        """Map one finite local point or reject a projective horizon."""
        local = QPointF(point)
        if not math.isfinite(local.x()) or not math.isfinite(local.y()):
            raise ValueError("projective input point must be finite")
        denominator_terms = (
            self.m13 * local.x(),
            self.m23 * local.y(),
            self.m33,
        )
        denominator = sum(denominator_terms)
        scale = max(*(abs(value) for value in denominator_terms), 1.0)
        if abs(denominator) <= _HORIZON_EPSILON * scale:
            raise ValueError("point maps to the projective horizon")
        return QPointF(
            (self.m11 * local.x() + self.m21 * local.y() + self.dx) / denominator,
            (self.m12 * local.x() + self.m22 * local.y() + self.dy) / denominator,
        )

    def inverse_map(self, point: QPointF) -> QPointF | None:
        """Map a scene point into local space when the result is usable."""
        inverse = self.inverted()
        if inverse is None:
            return None
        try:
            return inverse.map_point(point)
        except ValueError:
            return None

    def inverted(self) -> ProjectiveLayerTransform | None:
        """Return the inverse homography when Qt can compute it."""
        inverse, invertible = self.to_qtransform().inverted()
        return self.from_qtransform(inverse) if invertible else None

    def followed_by(
        self,
        next_transform: LayerTransform | ProjectiveLayerTransform,
    ) -> ProjectiveLayerTransform:
        """Return the explicit composition ``next_transform(self(point))``."""
        if not isinstance(next_transform, (LayerTransform, ProjectiveLayerTransform)):
            raise TypeError("next_transform must be a layer transform")
        composed = self.to_qtransform() * next_transform.to_qtransform()
        return self.from_qtransform(composed)

    def map_rect(self, rect: QRect | QRectF) -> QRectF:
        """Return the conservative finite bound of a local rectangle."""
        rectangle = QRectF(rect)
        return _bounding_rect(
            (
                self.map_point(rectangle.topLeft()),
                self.map_point(rectangle.topRight()),
                self.map_point(rectangle.bottomRight()),
                self.map_point(rectangle.bottomLeft()),
            )
        )

    def map_bounds(self, bounds: RasterBounds) -> LayerPlacement:
        """Return the conservative scene placement of local raster bounds."""
        rectangle = self.map_rect(
            QRectF(bounds.x, bounds.y, bounds.width, bounds.height)
        )
        return LayerPlacement(
            rectangle.x(),
            rectangle.y(),
            rectangle.width(),
            rectangle.height(),
        )


def _finite_quad(
    points: tuple[QPointF, QPointF, QPointF, QPointF],
    *,
    name: str,
) -> tuple[QPointF, QPointF, QPointF, QPointF]:
    """Detach and validate four finite quadrilateral points."""
    if len(points) != 4:
        raise ValueError(f"{name} quadrilateral must contain exactly four points")
    detached = tuple(QPointF(point) for point in points)
    if not all(
        math.isfinite(value) for point in detached for value in (point.x(), point.y())
    ):
        raise ValueError(f"{name} quadrilateral points must be finite")
    return detached[0], detached[1], detached[2], detached[3]


def _bounding_rect(points: tuple[QPointF, ...]) -> QRectF:
    """Return the axis-aligned finite bounds around mapped points."""
    left = min(point.x() for point in points)
    top = min(point.y() for point in points)
    right = max(point.x() for point in points)
    bottom = max(point.y() for point in points)
    return QRectF(left, top, right - left, bottom - top)


__all__ = ["ProjectiveLayerTransform"]
