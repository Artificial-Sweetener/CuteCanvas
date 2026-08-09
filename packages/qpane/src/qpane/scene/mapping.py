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

"""Authoritative common operations for affine and projective layer mappings."""

from __future__ import annotations

import math
from typing import TypeAlias

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QTransform

from .affine import LayerTransform
from .bilinear import BilinearLayerTransform
from .piecewise import PiecewiseLayerTransform
from .projective import ProjectiveLayerTransform
from .raster import RasterBounds

LayerMapping: TypeAlias = (
    LayerTransform
    | ProjectiveLayerTransform
    | PiecewiseLayerTransform
    | BilinearLayerTransform
)

_GEOMETRY_EPSILON = 1e-12


def layer_mapping_from_qtransform(transform: QTransform) -> LayerMapping:
    """Detach a Qt transform into its narrow authoritative mapping type."""
    if not isinstance(transform, QTransform):
        raise TypeError("transform must be a QTransform")
    if transform.isAffine():
        return LayerTransform.from_qtransform(transform)
    return ProjectiveLayerTransform.from_qtransform(transform)


def compose_layer_mappings(
    first: LayerMapping,
    second: LayerMapping,
) -> LayerMapping:
    """Return the mapping that applies ``first`` and then ``second``."""
    _require_mapping(first, name="first")
    _require_mapping(second, name="second")
    if isinstance(first, (PiecewiseLayerTransform, BilinearLayerTransform)):
        if isinstance(second, (PiecewiseLayerTransform, BilinearLayerTransform)):
            raise TypeError("composition of two bounded mappings is unsupported")
        return first.followed_by(second)
    if isinstance(second, (PiecewiseLayerTransform, BilinearLayerTransform)):
        return second.preceded_by(first)
    return layer_mapping_from_qtransform(first.to_qtransform() * second.to_qtransform())


def inverse_mapping_linearization(
    mapping: LayerMapping,
    source_point: QPointF,
) -> LayerTransform | None:
    """Return the scene-to-source differential at one source-space point."""
    _require_mapping(mapping, name="mapping")
    if not isinstance(source_point, QPointF):
        raise TypeError("source_point must be QPointF")
    if not math.isfinite(source_point.x()) or not math.isfinite(source_point.y()):
        raise ValueError("source_point coordinates must be finite")
    forward = _forward_mapping_linearization(mapping, source_point)
    return forward.inverted()


def mapped_layer_quad(
    mapping: LayerMapping,
    bounds: RasterBounds,
) -> tuple[QPointF, QPointF, QPointF, QPointF]:
    """Map ordered local raster corners into scene coordinates."""
    _require_mapping(mapping, name="mapping")
    if not isinstance(bounds, RasterBounds):
        raise TypeError("bounds must be RasterBounds")
    points = tuple(
        mapping.map_point(point)
        for point in (
            QPointF(bounds.x, bounds.y),
            QPointF(bounds.right, bounds.y),
            QPointF(bounds.right, bounds.bottom),
            QPointF(bounds.x, bounds.bottom),
        )
    )
    return points[0], points[1], points[2], points[3]


def conservative_mapping_scale(
    mapping: LayerMapping,
    bounds: RasterBounds,
) -> float:
    """Return a finite upper bound for local-to-scene differential scale."""
    _require_mapping(mapping, name="mapping")
    if not isinstance(bounds, RasterBounds):
        raise TypeError("bounds must be RasterBounds")
    if isinstance(mapping, PiecewiseLayerTransform):
        return max(
            max(
                math.hypot(patch.transform.m11, patch.transform.m12),
                math.hypot(patch.transform.m21, patch.transform.m22),
            )
            for patch in mapping.patches
        )
    if isinstance(mapping, BilinearLayerTransform):
        return max(
            max(
                math.hypot(linear.m11, linear.m12),
                math.hypot(linear.m21, linear.m22),
            )
            for point in (
                *mapping.source_boundary,
                mapping.point_at(0.5, 0.5),
            )
            for linear in (mapping.linearization(point),)
        )
    if isinstance(mapping, LayerTransform):
        return max(
            math.hypot(mapping.m11, mapping.m12),
            math.hypot(mapping.m21, mapping.m22),
        )
    transform = mapping.to_qtransform()
    corners = (
        (float(bounds.x), float(bounds.y)),
        (float(bounds.right), float(bounds.y)),
        (float(bounds.right), float(bounds.bottom)),
        (float(bounds.x), float(bounds.bottom)),
    )
    denominators = tuple(
        transform.m13() * x + transform.m23() * y + transform.m33() for x, y in corners
    )
    minimum_denominator = min(abs(value) for value in denominators)
    if minimum_denominator <= _GEOMETRY_EPSILON:
        return math.inf
    maximum_denominator = max(abs(value) for value in denominators)
    x_numerators = tuple(
        transform.m11() * x + transform.m21() * y + transform.m31() for x, y in corners
    )
    y_numerators = tuple(
        transform.m12() * x + transform.m22() * y + transform.m32() for x, y in corners
    )
    inverse_denominator_squared = 1.0 / (minimum_denominator**2)
    derivative_bounds = (
        (
            abs(transform.m11()) * maximum_denominator
            + max(abs(value) for value in x_numerators) * abs(transform.m13())
        )
        * inverse_denominator_squared,
        (
            abs(transform.m21()) * maximum_denominator
            + max(abs(value) for value in x_numerators) * abs(transform.m23())
        )
        * inverse_denominator_squared,
        (
            abs(transform.m12()) * maximum_denominator
            + max(abs(value) for value in y_numerators) * abs(transform.m13())
        )
        * inverse_denominator_squared,
        (
            abs(transform.m22()) * maximum_denominator
            + max(abs(value) for value in y_numerators) * abs(transform.m23())
        )
        * inverse_denominator_squared,
    )
    return math.sqrt(sum(value * value for value in derivative_bounds))


def validate_layer_mapping(mapping: LayerMapping, bounds: RasterBounds) -> None:
    """Reject a mapping that cannot safely present one finite source rectangle."""
    _require_mapping(mapping, name="mapping")
    if not isinstance(bounds, RasterBounds):
        raise TypeError("bounds must be RasterBounds")
    if not mapping.is_invertible:
        raise ValueError("layer mapping must be invertible")
    if isinstance(mapping, (PiecewiseLayerTransform, BilinearLayerTransform)):
        source = _boundary_rect(mapping.source_boundary)
        expected = QRectF(bounds.x, bounds.y, bounds.width, bounds.height)
        if not expected.contains(source):
            raise ValueError(
                "bounded source boundary must stay inside layer raster bounds"
            )
        return
    denominators = _corner_denominators(mapping.to_qtransform(), bounds)
    denominator_scale = max(*(abs(value) for value in denominators), 1.0)
    tolerance = _GEOMETRY_EPSILON * denominator_scale
    if any(abs(value) <= tolerance for value in denominators):
        raise ValueError("layer mapping horizon touches the source bounds")
    if min(denominators) < 0.0 < max(denominators):
        raise ValueError("layer mapping horizon crosses the source bounds")
    target = mapped_layer_quad(mapping, bounds)
    _validate_convex_quad(target)


def _corner_denominators(
    transform: QTransform,
    bounds: RasterBounds,
) -> tuple[float, float, float, float]:
    """Return homogeneous denominators at all source-bound corners."""
    return (
        transform.m13() * bounds.x + transform.m23() * bounds.y + transform.m33(),
        transform.m13() * bounds.right + transform.m23() * bounds.y + transform.m33(),
        transform.m13() * bounds.right
        + transform.m23() * bounds.bottom
        + transform.m33(),
        transform.m13() * bounds.x + transform.m23() * bounds.bottom + transform.m33(),
    )


def _forward_mapping_linearization(
    mapping: LayerMapping,
    source_point: QPointF,
) -> LayerTransform:
    """Return the local source-to-scene differential for one mapping."""
    if isinstance(mapping, LayerTransform):
        return LayerTransform(
            m11=mapping.m11,
            m12=mapping.m12,
            m21=mapping.m21,
            m22=mapping.m22,
        )
    if isinstance(mapping, PiecewiseLayerTransform):
        patch = next(
            (
                candidate
                for candidate in mapping.patches
                if candidate.contains_source(source_point)
            ),
            None,
        )
        if patch is None:
            raise ValueError("source_point lies outside the piecewise mapping")
        transform = patch.transform
        return LayerTransform(
            m11=transform.m11,
            m12=transform.m12,
            m21=transform.m21,
            m22=transform.m22,
        )
    if isinstance(mapping, BilinearLayerTransform):
        return mapping.linearization(source_point)
    transform = mapping.to_qtransform()
    x = source_point.x()
    y = source_point.y()
    denominator = transform.m13() * x + transform.m23() * y + transform.m33()
    scale = max(abs(denominator), abs(x), abs(y), 1.0)
    if abs(denominator) <= _GEOMETRY_EPSILON * scale:
        raise ValueError("source_point lies on the mapping horizon")
    x_numerator = transform.m11() * x + transform.m21() * y + transform.m31()
    y_numerator = transform.m12() * x + transform.m22() * y + transform.m32()
    squared = denominator * denominator
    return LayerTransform(
        m11=(transform.m11() * denominator - x_numerator * transform.m13()) / squared,
        m12=(transform.m12() * denominator - y_numerator * transform.m13()) / squared,
        m21=(transform.m21() * denominator - x_numerator * transform.m23()) / squared,
        m22=(transform.m22() * denominator - y_numerator * transform.m23()) / squared,
    )


def _validate_convex_quad(
    points: tuple[QPointF, QPointF, QPointF, QPointF],
) -> None:
    """Reject collapsed, concave, or self-intersecting mapped boundaries."""
    coordinate_scale = max(
        *(abs(value) for point in points for value in (point.x(), point.y())),
        1.0,
    )
    tolerance = _GEOMETRY_EPSILON * coordinate_scale * coordinate_scale
    turns = tuple(
        _cross(
            points[(index + 1) % 4] - points[index],
            points[(index + 2) % 4] - points[(index + 1) % 4],
        )
        for index in range(4)
    )
    if any(not math.isfinite(turn) or abs(turn) <= tolerance for turn in turns):
        raise ValueError("layer mapping produces a degenerate quadrilateral")
    if min(turns) < 0.0 < max(turns):
        raise ValueError("layer mapping produces a non-convex quadrilateral")


def _cross(first: QPointF, second: QPointF) -> float:
    """Return the scalar cross product of two planar vectors."""
    return first.x() * second.y() - first.y() * second.x()


def _require_mapping(mapping: object, *, name: str) -> None:
    """Reject values outside the supported layer-mapping contract."""
    if not isinstance(
        mapping,
        (
            LayerTransform,
            ProjectiveLayerTransform,
            PiecewiseLayerTransform,
            BilinearLayerTransform,
        ),
    ):
        raise TypeError(f"{name} must be a layer mapping")


def _boundary_rect(points: tuple[QPointF, ...]) -> QRectF:
    """Return the exact axis-aligned bound of one finite boundary."""
    left = min(point.x() for point in points)
    top = min(point.y() for point in points)
    right = max(point.x() for point in points)
    bottom = max(point.y() for point in points)
    return QRectF(left, top, right - left, bottom - top)


__all__ = [
    "LayerMapping",
    "compose_layer_mappings",
    "conservative_mapping_scale",
    "inverse_mapping_linearization",
    "layer_mapping_from_qtransform",
    "mapped_layer_quad",
    "validate_layer_mapping",
]
