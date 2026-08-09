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

"""Full-source bilinear mapping for a quadrilateral with one joined edge."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRect, QRectF
from PySide6.QtGui import QPainterPath, QPolygonF

from .affine import LayerTransform
from .model import LayerPlacement
from .piecewise_topology import (
    bounding_rect,
    finite_boundary,
    finite_point,
    validate_simple_boundary,
)
from .projective import ProjectiveLayerTransform
from .raster import RasterBounds

_COORDINATE_TOLERANCE = 1e-9
_PATH_STEPS = 32


@dataclass(frozen=True, slots=True)
class BilinearLayerTransform:
    """Map a complete source quadrilateral onto a triangle by joining one edge."""

    source_boundary: tuple[QPointF, QPointF, QPointF, QPointF]
    target_boundary: tuple[QPointF, QPointF, QPointF, QPointF]

    def __post_init__(self) -> None:
        """Validate a convex source and one consistently wound joined target."""
        source = finite_boundary(self.source_boundary, name="source")
        if len(source) != 4:
            raise ValueError("bilinear source boundary must contain four points")
        source_winding = validate_simple_boundary(source, name="source")
        target = tuple(
            finite_point(point, name="target boundary")
            for point in self.target_boundary
        )
        if len(target) != 4 or target[0] != target[1]:
            raise ValueError("bilinear target boundary must join its first edge")
        compact_target = (target[0], target[2], target[3])
        if validate_simple_boundary(compact_target, name="target") != source_winding:
            raise ValueError("bilinear boundaries must preserve winding")
        object.__setattr__(self, "source_boundary", source)
        object.__setattr__(self, "target_boundary", target)

    @property
    def is_invertible(self) -> bool:
        """Return True because every target interior point has one source point."""
        return True

    def map_point(self, point: QPointF) -> QPointF:
        """Map one point from the complete source quadrilateral into the triangle."""
        source = finite_point(point, name="bilinear input")
        coordinates = _inverse_bilinear_quad(self.source_boundary, source)
        if coordinates is None:
            raise ValueError("point lies outside the bilinear source boundary")
        return _bilinear_point(self.target_boundary, *coordinates)

    def inverse_map(self, point: QPointF) -> QPointF | None:
        """Map one target-triangle point into the complete source quadrilateral."""
        try:
            target = finite_point(point, name="bilinear target")
        except ValueError:
            return None
        coordinates = _inverse_joined_target(self.target_boundary, target)
        return (
            None
            if coordinates is None
            else _bilinear_point(self.source_boundary, *coordinates)
        )

    def linearization(self, source_point: QPointF) -> LayerTransform:
        """Return the exact local source-to-target differential at one point."""
        coordinates = _inverse_bilinear_quad(self.source_boundary, source_point)
        if coordinates is None:
            raise ValueError("source_point lies outside the bilinear mapping")
        u, v = coordinates
        source_u, source_v = _bilinear_derivatives(self.source_boundary, u, v)
        target_u, target_v = _bilinear_derivatives(self.target_boundary, u, v)
        determinant = source_u.x() * source_v.y() - source_u.y() * source_v.x()
        scale = max(
            abs(source_u.x()),
            abs(source_u.y()),
            abs(source_v.x()),
            abs(source_v.y()),
            1.0,
        )
        if abs(determinant) <= _COORDINATE_TOLERANCE * scale * scale:
            raise ValueError("bilinear source differential is singular")
        m11 = (target_u.x() * source_v.y() - target_v.x() * source_u.y()) / determinant
        m21 = (target_v.x() * source_u.x() - target_u.x() * source_v.x()) / determinant
        m12 = (target_u.y() * source_v.y() - target_v.y() * source_u.y()) / determinant
        m22 = (target_v.y() * source_u.x() - target_u.y() * source_v.x()) / determinant
        return LayerTransform(m11=m11, m12=m12, m21=m21, m22=m22)

    def followed_by(
        self,
        next_transform: LayerTransform | ProjectiveLayerTransform,
    ) -> BilinearLayerTransform:
        """Apply one global affine or projective mapping after this mapping."""
        if not isinstance(next_transform, (LayerTransform, ProjectiveLayerTransform)):
            raise TypeError("next_transform must be a global layer transform")
        return BilinearLayerTransform(
            self.source_boundary,
            tuple(next_transform.map_point(point) for point in self.target_boundary),
        )

    def preceded_by(
        self,
        previous_transform: LayerTransform | ProjectiveLayerTransform,
    ) -> BilinearLayerTransform:
        """Apply one global affine or projective mapping before this mapping."""
        if not isinstance(
            previous_transform, (LayerTransform, ProjectiveLayerTransform)
        ):
            raise TypeError("previous_transform must be a global layer transform")
        inverse = previous_transform.inverted()
        if inverse is None:
            raise ValueError("previous layer transform must be invertible")
        return BilinearLayerTransform(
            tuple(inverse.map_point(point) for point in self.source_boundary),
            self.target_boundary,
        )

    def map_path(self, path: QPainterPath) -> QPainterPath:
        """Map one filled path through a deterministic sampled boundary."""
        clipped = path.intersected(_boundary_path(self.source_boundary))
        return _map_path(clipped, self.map_point)

    def inverse_map_path(self, path: QPainterPath) -> QPainterPath:
        """Inverse-map one filled path through a deterministic sampled boundary."""
        clipped = path.intersected(_boundary_path(self.target_boundary))
        return _map_path(
            clipped,
            self.inverse_map,
            joined_source_edge=(self.source_boundary[0], self.source_boundary[1]),
            joined_target=self.target_boundary[0],
        )

    def map_rect(self, rect: QRect | QRectF) -> QRectF:
        """Return conservative mapped bounds for a source rectangle."""
        return self.map_path(_rectangle_path(rect)).boundingRect()

    def inverse_map_rect(self, rect: QRect | QRectF) -> QRectF:
        """Return conservative inverse-mapped bounds for a target rectangle."""
        return self.inverse_map_path(_rectangle_path(rect)).boundingRect()

    def map_bounds(self, bounds: RasterBounds) -> LayerPlacement:
        """Return conservative scene placement of the mapped source boundary."""
        if not isinstance(bounds, RasterBounds):
            raise TypeError("bounds must be RasterBounds")
        rectangle = bounding_rect(self.target_boundary)
        return LayerPlacement(
            rectangle.x(),
            rectangle.y(),
            rectangle.width(),
            rectangle.height(),
        )

    def point_at(self, u: float, v: float, *, target: bool = False) -> QPointF:
        """Return one normalized source or target point for rendering projection."""
        if not all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in (u, v)):
            raise ValueError("normalized coordinates must be finite and within [0, 1]")
        return _bilinear_point(
            self.target_boundary if target else self.source_boundary,
            float(u),
            float(v),
        )


def _bilinear_point(
    quad: tuple[QPointF, QPointF, QPointF, QPointF],
    u: float,
    v: float,
) -> QPointF:
    """Evaluate one conventional clockwise bilinear quadrilateral point."""
    top = quad[0] * (1.0 - u) + quad[1] * u
    bottom = quad[3] * (1.0 - u) + quad[2] * u
    return top * (1.0 - v) + bottom * v


def _bilinear_derivatives(
    quad: tuple[QPointF, QPointF, QPointF, QPointF],
    u: float,
    v: float,
) -> tuple[QPointF, QPointF]:
    """Return derivatives with respect to normalized horizontal and vertical axes."""
    derivative_u = (quad[1] - quad[0]) * (1.0 - v) + (quad[2] - quad[3]) * v
    derivative_v = (quad[3] - quad[0]) * (1.0 - u) + (quad[2] - quad[1]) * u
    return derivative_u, derivative_v


def _inverse_bilinear_quad(
    quad: tuple[QPointF, QPointF, QPointF, QPointF],
    point: QPointF,
) -> tuple[float, float] | None:
    """Solve normalized coordinates for one point in a convex bilinear quad."""
    horizontal = quad[1] - quad[0]
    vertical = quad[3] - quad[0]
    relative = point - quad[0]
    determinant = horizontal.x() * vertical.y() - horizontal.y() * vertical.x()
    if abs(determinant) <= 1e-18:
        u = v = 0.5
    else:
        u = (relative.x() * vertical.y() - relative.y() * vertical.x()) / determinant
        v = (
            horizontal.x() * relative.y() - horizontal.y() * relative.x()
        ) / determinant
    for _iteration in range(16):
        current = _bilinear_point(quad, u, v)
        error = current - point
        derivative_u, derivative_v = _bilinear_derivatives(quad, u, v)
        jacobian = (
            derivative_u.x() * derivative_v.y() - derivative_u.y() * derivative_v.x()
        )
        if abs(jacobian) <= 1e-18:
            break
        delta_u = (
            error.x() * derivative_v.y() - error.y() * derivative_v.x()
        ) / jacobian
        delta_v = (
            derivative_u.x() * error.y() - derivative_u.y() * error.x()
        ) / jacobian
        u -= delta_u
        v -= delta_v
        if abs(delta_u) + abs(delta_v) <= 1e-12:
            break
    scale = max(
        *(abs(value) for vertex in quad for value in (vertex.x(), vertex.y())),
        abs(point.x()),
        abs(point.y()),
        1.0,
    )
    residual = _bilinear_point(quad, u, v) - point
    if math.hypot(residual.x(), residual.y()) > _COORDINATE_TOLERANCE * scale:
        return None
    if not (-_COORDINATE_TOLERANCE <= u <= 1.0 + _COORDINATE_TOLERANCE):
        return None
    if not (-_COORDINATE_TOLERANCE <= v <= 1.0 + _COORDINATE_TOLERANCE):
        return None
    return min(1.0, max(0.0, u)), min(1.0, max(0.0, v))


def _inverse_joined_target(
    target: tuple[QPointF, QPointF, QPointF, QPointF],
    point: QPointF,
) -> tuple[float, float] | None:
    """Solve normalized coordinates in a triangle whose first edge is joined."""
    apex = target[0]
    right = target[2] - apex
    left = target[3] - apex
    relative = point - apex
    determinant = left.x() * right.y() - left.y() * right.x()
    if abs(determinant) <= 1e-18:
        return None
    left_weight = (relative.x() * right.y() - relative.y() * right.x()) / determinant
    right_weight = (left.x() * relative.y() - left.y() * relative.x()) / determinant
    v = left_weight + right_weight
    tolerance = _COORDINATE_TOLERANCE
    if left_weight < -tolerance or right_weight < -tolerance or v > 1.0 + tolerance:
        return None
    if v <= tolerance:
        return 0.5, 0.0
    return min(1.0, max(0.0, right_weight / v)), min(1.0, max(0.0, v))


def _map_path(
    path: QPainterPath,
    mapper: Callable[[QPointF], QPointF | None],
    *,
    joined_source_edge: tuple[QPointF, QPointF] | None = None,
    joined_target: QPointF | None = None,
) -> QPainterPath:
    """Map flattened fill polygons with bounded subdivision per segment."""
    result = QPainterPath()
    result.setFillRule(path.fillRule())
    for polygon in path.toSubpathPolygons():
        if polygon.isEmpty():
            continue
        mapped_points: list[QPointF] = []
        points = tuple(QPointF(point) for point in polygon)
        for index, start in enumerate(points):
            end = points[(index + 1) % len(points)]
            for step in range(_PATH_STEPS):
                ratio = step / _PATH_STEPS
                sampled = start * (1.0 - ratio) + end * ratio
                if (
                    joined_source_edge is not None
                    and joined_target is not None
                    and _points_close(sampled, joined_target)
                ):
                    for joined_point in joined_source_edge:
                        if not mapped_points or not _points_close(
                            mapped_points[-1], joined_point
                        ):
                            mapped_points.append(QPointF(joined_point))
                    continue
                mapped = mapper(sampled)
                if mapped is not None:
                    mapped_points.append(mapped)
        if len(mapped_points) >= 3:
            result.addPolygon(QPolygonF(mapped_points))
            result.closeSubpath()
    return result


def _points_close(first: QPointF, second: QPointF) -> bool:
    """Return whether two coordinates agree at mapping-boundary precision."""
    return math.hypot(first.x() - second.x(), first.y() - second.y()) <= 1e-8


def _rectangle_path(rect: QRect | QRectF) -> QPainterPath:
    """Return one detached rectangular painter path."""
    path = QPainterPath()
    path.addRect(QRectF(rect))
    return path


def _boundary_path(points: tuple[QPointF, ...]) -> QPainterPath:
    """Return one closed boundary path with a joined vertex retained."""
    path = QPainterPath()
    path.addPolygon(QPolygonF(points))
    path.closeSubpath()
    return path


__all__ = ["BilinearLayerTransform"]
