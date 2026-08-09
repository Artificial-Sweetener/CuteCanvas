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

"""Conservative presentation density for finite projective source regions."""

from __future__ import annotations

import math

from PySide6.QtCore import QRectF
from PySide6.QtGui import QTransform

from .panel_mapping import PanelLayerMapping, PiecewisePanelMapping

_DENOMINATOR_EPSILON = 1e-12


def conservative_transform_scale(
    transform: PanelLayerMapping,
    source_rect: QRectF,
) -> float:
    """Return an upper bound for differential scale over a finite source rect."""
    if isinstance(transform, PiecewisePanelMapping):
        return max(
            conservative_transform_scale(patch.transform, source_rect)
            for patch in transform.patches
        )
    if not isinstance(transform, QTransform):
        raise TypeError("transform must be a panel layer mapping")
    rectangle = QRectF(source_rect).normalized()
    if rectangle.isEmpty():
        return 0.0
    if transform.isAffine():
        return max(
            math.hypot(transform.m11(), transform.m12()),
            math.hypot(transform.m21(), transform.m22()),
        )
    corners = (
        (rectangle.left(), rectangle.top()),
        (rectangle.right(), rectangle.top()),
        (rectangle.right(), rectangle.bottom()),
        (rectangle.left(), rectangle.bottom()),
    )
    denominators = tuple(_denominator(transform, x, y) for x, y in corners)
    minimum_denominator = min(abs(value) for value in denominators)
    if minimum_denominator <= _DENOMINATOR_EPSILON:
        return math.inf
    maximum_denominator = max(abs(value) for value in denominators)
    maximum_x_numerator = max(abs(_x_numerator(transform, x, y)) for x, y in corners)
    maximum_y_numerator = max(abs(_y_numerator(transform, x, y)) for x, y in corners)
    inverse_denominator_squared = 1.0 / (minimum_denominator**2)
    derivative_bounds = (
        (
            abs(transform.m11()) * maximum_denominator
            + maximum_x_numerator * abs(transform.m13())
        )
        * inverse_denominator_squared,
        (
            abs(transform.m21()) * maximum_denominator
            + maximum_x_numerator * abs(transform.m23())
        )
        * inverse_denominator_squared,
        (
            abs(transform.m12()) * maximum_denominator
            + maximum_y_numerator * abs(transform.m13())
        )
        * inverse_denominator_squared,
        (
            abs(transform.m22()) * maximum_denominator
            + maximum_y_numerator * abs(transform.m23())
        )
        * inverse_denominator_squared,
    )
    return math.sqrt(sum(value * value for value in derivative_bounds))


def _denominator(transform: QTransform, x: float, y: float) -> float:
    """Return the homogeneous denominator at one source point."""
    return transform.m13() * x + transform.m23() * y + transform.m33()


def _x_numerator(transform: QTransform, x: float, y: float) -> float:
    """Return the homogeneous x numerator at one source point."""
    return transform.m11() * x + transform.m21() * y + transform.m31()


def _y_numerator(transform: QTransform, x: float, y: float) -> float:
    """Return the homogeneous y numerator at one source point."""
    return transform.m12() * x + transform.m22() * y + transform.m32()


__all__ = ["conservative_transform_scale"]
