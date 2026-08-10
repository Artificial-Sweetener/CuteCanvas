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
"""Scene-aligned affine frames for finite nonlinear layer mappings."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF

from .affine import LayerTransform
from .bilinear import BilinearLayerTransform
from .mapping import LayerMapping, compose_layer_mappings
from .piecewise import PiecewiseLayerTransform
from .transform_contracts import (
    TransformHandle,
    TransformLocalBounds,
    TransformModifiers,
)

BoundedLayerMapping = PiecewiseLayerTransform | BilinearLayerTransform


class BoundedAffineFrame:
    """Own one rectangular affine frame around a nonlinear mapped result."""

    def __init__(
        self,
        bounds: TransformLocalBounds,
        mapping: BoundedLayerMapping,
    ) -> None:
        """Resolve the current result's exact scene-aligned bounding box."""
        source_rectangle = QRectF(bounds.x, bounds.y, bounds.width, bounds.height)
        rectangle = (
            _boundary_bounds(mapping.target_boundary)
            if _contains_boundary(source_rectangle, mapping.source_boundary)
            else mapping.map_rect(source_rectangle)
        )
        self._frame = TransformLocalBounds(
            rectangle.x(),
            rectangle.y(),
            rectangle.width(),
            rectangle.height(),
        )
        self._mapping = mapping

    def point(self, handle: TransformHandle) -> QPointF:
        """Return one affine control on the scene bounding box."""
        return self._frame.point(handle)

    def center(self) -> QPointF:
        """Return the scene bounding box center."""
        return self._frame.center

    def scale_for_drag(
        self,
        handle: TransformHandle,
        pointer_origin: QPointF,
        pointer_position: QPointF,
        modifiers: TransformModifiers,
    ) -> LayerMapping | None:
        """Scale the mapped result around its opposite box control or center."""
        anchor = (
            self._frame.center
            if modifiers.about_center
            else self._frame.opposite(handle)
        )
        current = self._frame.point(handle)
        desired = current + (pointer_position - pointer_origin)
        denominator_x = current.x() - anchor.x()
        denominator_y = current.y() - anchor.y()
        scale_x = (
            1.0
            if abs(denominator_x) <= 1e-12
            else (desired.x() - anchor.x()) / denominator_x
        )
        scale_y = (
            1.0
            if abs(denominator_y) <= 1e-12
            else (desired.y() - anchor.y()) / denominator_y
        )
        if denominator_x != 0.0 and denominator_y != 0.0 and modifiers.proportional:
            initial_vector = current - anchor
            desired_vector = desired - anchor
            magnitude = QPointF.dotProduct(initial_vector, initial_vector)
            if magnitude <= 1e-12:
                return None
            uniform = QPointF.dotProduct(desired_vector, initial_vector) / magnitude
            scale_x = uniform
            scale_y = uniform
        if abs(scale_x * scale_y) <= 1e-12:
            return None
        delta = LayerTransform(
            m11=scale_x,
            m22=scale_y,
            dx=anchor.x() * (1.0 - scale_x),
            dy=anchor.y() * (1.0 - scale_y),
        )
        candidate = compose_layer_mappings(self._mapping, delta)
        return candidate if candidate.is_invertible else None

    def skew_for_drag(
        self,
        handle: TransformHandle,
        pointer_origin: QPointF,
        pointer_position: QPointF,
        modifiers: TransformModifiers,
    ) -> LayerMapping | None:
        """Skew one scene-box side while preserving its opposite side or center."""
        if handle in {
            TransformHandle.TOP_LEFT,
            TransformHandle.TOP_RIGHT,
            TransformHandle.BOTTOM_RIGHT,
            TransformHandle.BOTTOM_LEFT,
        }:
            return None
        anchor = (
            self._frame.center
            if modifiers.about_center
            else self._frame.opposite(handle)
        )
        current = self._frame.point(handle)
        desired = current + (pointer_position - pointer_origin)
        if handle in {TransformHandle.TOP, TransformHandle.BOTTOM}:
            denominator = current.y() - anchor.y()
            if abs(denominator) <= 1e-12:
                return None
            shear = (desired.x() - current.x()) / denominator
            delta = LayerTransform(m21=shear, dx=-shear * anchor.y())
        else:
            denominator = current.x() - anchor.x()
            if abs(denominator) <= 1e-12:
                return None
            shear = (desired.y() - current.y()) / denominator
            delta = LayerTransform(m12=shear, dy=-shear * anchor.x())
        candidate = compose_layer_mappings(self._mapping, delta)
        return candidate if candidate.is_invertible else None


def _boundary_bounds(boundary: tuple[QPointF, ...]) -> QRectF:
    """Return the exact axis-aligned bounds of detached finite points."""
    left = min(point.x() for point in boundary)
    top = min(point.y() for point in boundary)
    right = max(point.x() for point in boundary)
    bottom = max(point.y() for point in boundary)
    return QRectF(left, top, right - left, bottom - top)


def _contains_boundary(rectangle: QRectF, boundary: tuple[QPointF, ...]) -> bool:
    """Return whether local manipulation bounds contain the finite source cage."""
    scale = max(
        abs(rectangle.left()),
        abs(rectangle.top()),
        abs(rectangle.right()),
        abs(rectangle.bottom()),
        rectangle.width(),
        rectangle.height(),
        1.0,
    )
    tolerance = 1e-12 * scale
    return all(
        rectangle.left() - tolerance <= point.x() <= rectangle.right() + tolerance
        and rectangle.top() - tolerance <= point.y() <= rectangle.bottom() + tolerance
        for point in boundary
    )


__all__ = ["BoundedAffineFrame", "BoundedLayerMapping"]
