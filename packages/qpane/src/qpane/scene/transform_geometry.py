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
"""Exact affine geometry for interactive layer transform handles."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF

from .affine import LayerTransform
from .bilinear import BilinearLayerTransform
from .bounded_affine import BoundedAffineFrame
from .mapping import LayerMapping, compose_layer_mappings
from .piecewise import PiecewiseLayerTransform
from .transform_contracts import (
    TransformHandle,
    TransformLocalBounds,
    TransformModifiers,
    TransformOperation,
    TransformOperationKind,
)


class AffineTransformGeometry:
    """Derive exact affine previews from one durable transform-box base."""

    def __init__(
        self,
        bounds: TransformLocalBounds,
        initial_transform: LayerMapping,
    ) -> None:
        """Bind source-local bounds and one invertible durable transform."""
        if not initial_transform.is_invertible:
            raise ValueError("initial transform must be invertible")
        self._bounds = bounds
        self._initial = initial_transform
        self._bounded_frame = (
            BoundedAffineFrame(bounds, initial_transform)
            if isinstance(
                initial_transform,
                (PiecewiseLayerTransform, BilinearLayerTransform),
            )
            else None
        )

    @property
    def bounds(self) -> TransformLocalBounds:
        """Return immutable source-local target bounds."""
        return self._bounds

    @property
    def initial_transform(self) -> LayerMapping:
        """Return the immutable durable transform base."""
        return self._initial

    def scene_point(self, handle: TransformHandle) -> QPointF:
        """Return one handle center in scene coordinates."""
        if self._bounded_frame is not None:
            return self._bounded_frame.point(handle)
        return self._initial.map_point(self._bounds.point(handle))

    def scene_center(self) -> QPointF:
        """Return the transform reference center in scene coordinates."""
        if self._bounded_frame is not None:
            return self._bounded_frame.center()
        return self._initial.map_point(self._bounds.center)

    def transform_for_drag(
        self,
        operation: TransformOperation,
        pointer_origin: QPointF,
        pointer_position: QPointF,
        modifiers: TransformModifiers,
    ) -> LayerMapping | None:
        """Return an exact preview transform for one pointer displacement."""
        if operation.kind is TransformOperationKind.MOVE:
            delta = pointer_position - pointer_origin
            return compose_layer_mappings(
                self._initial,
                LayerTransform(dx=delta.x(), dy=delta.y()),
            )
        if operation.kind is TransformOperationKind.ROTATE:
            return self._rotation(pointer_origin, pointer_position, modifiers)
        if operation.handle is None:
            return None
        if operation.kind is TransformOperationKind.SKEW:
            return self._skew(
                operation.handle,
                pointer_origin,
                pointer_position,
                modifiers,
            )
        return self._scale(
            operation.handle,
            pointer_origin,
            pointer_position,
            modifiers,
        )

    def _scale(
        self,
        handle: TransformHandle,
        pointer_origin: QPointF,
        pointer_position: QPointF,
        modifiers: TransformModifiers,
    ) -> LayerMapping | None:
        """Scale local geometry about its opposite handle or center."""
        if self._bounded_frame is not None:
            return self._bounded_frame.scale_for_drag(
                handle,
                pointer_origin,
                pointer_position,
                modifiers,
            )
        anchor = (
            self._bounds.center
            if modifiers.about_center
            else self._bounds.opposite(handle)
        )
        anchor_scene = self._initial.map_point(anchor)
        handle_local = self._bounds.point(handle)
        handle_scene = self._initial.map_point(handle_local)
        desired_scene = handle_scene + (pointer_position - pointer_origin)
        desired_local = self._initial.inverse_map(desired_scene)
        if desired_local is None:
            return None
        denominator_x = handle_local.x() - anchor.x()
        denominator_y = handle_local.y() - anchor.y()
        scale_x = (
            1.0
            if abs(denominator_x) <= 1e-12
            else (desired_local.x() - anchor.x()) / denominator_x
        )
        scale_y = (
            1.0
            if abs(denominator_y) <= 1e-12
            else (desired_local.y() - anchor.y()) / denominator_y
        )
        corner = denominator_x != 0.0 and denominator_y != 0.0
        if corner and modifiers.proportional:
            initial_vector = handle_scene - anchor_scene
            desired_vector = desired_scene - anchor_scene
            magnitude = QPointF.dotProduct(initial_vector, initial_vector)
            if magnitude <= 1e-12:
                return None
            uniform = QPointF.dotProduct(desired_vector, initial_vector) / magnitude
            scale_x = uniform
            scale_y = uniform
        local_scale = LayerTransform(
            m11=scale_x,
            m22=scale_y,
            dx=anchor.x() * (1.0 - scale_x),
            dy=anchor.y() * (1.0 - scale_y),
        )
        candidate = compose_layer_mappings(local_scale, self._initial)
        return candidate if candidate is not None and candidate.is_invertible else None

    def _rotation(
        self,
        pointer_origin: QPointF,
        pointer_position: QPointF,
        modifiers: TransformModifiers,
    ) -> LayerMapping | None:
        """Rotate scene geometry about the transformed content center."""
        pivot = self.scene_center()
        origin_vector = pointer_origin - pivot
        current_vector = pointer_position - pivot
        if (
            min(
                QPointF.dotProduct(origin_vector, origin_vector),
                QPointF.dotProduct(current_vector, current_vector),
            )
            <= 1e-12
        ):
            return None
        delta = math.atan2(current_vector.y(), current_vector.x()) - math.atan2(
            origin_vector.y(), origin_vector.x()
        )
        if modifiers.snap_rotation:
            increment = math.pi / 12.0
            delta = round(delta / increment) * increment
        cosine = math.cos(delta)
        sine = math.sin(delta)
        rotation = LayerTransform(
            m11=cosine,
            m12=sine,
            m21=-sine,
            m22=cosine,
            dx=pivot.x() - cosine * pivot.x() + sine * pivot.y(),
            dy=pivot.y() - sine * pivot.x() - cosine * pivot.y(),
        )
        candidate = compose_layer_mappings(self._initial, rotation)
        return candidate if candidate.is_invertible else None

    def _skew(
        self,
        handle: TransformHandle,
        pointer_origin: QPointF,
        pointer_position: QPointF,
        modifiers: TransformModifiers,
    ) -> LayerMapping | None:
        """Skew one side in local space about the opposite side or center."""
        if self._bounded_frame is not None:
            return self._bounded_frame.skew_for_drag(
                handle,
                pointer_origin,
                pointer_position,
                modifiers,
            )
        if handle in {
            TransformHandle.TOP_LEFT,
            TransformHandle.TOP_RIGHT,
            TransformHandle.BOTTOM_RIGHT,
            TransformHandle.BOTTOM_LEFT,
        }:
            return None
        anchor = (
            self._bounds.center
            if modifiers.about_center
            else self._bounds.opposite(handle)
        )
        handle_local = self._bounds.point(handle)
        handle_scene = self._initial.map_point(handle_local)
        desired_local = self._initial.inverse_map(
            handle_scene + (pointer_position - pointer_origin)
        )
        if desired_local is None:
            return None
        if handle in {TransformHandle.TOP, TransformHandle.BOTTOM}:
            denominator = handle_local.y() - anchor.y()
            if abs(denominator) <= 1e-12:
                return None
            shear = (desired_local.x() - handle_local.x()) / denominator
            local_skew = LayerTransform(m21=shear, dx=-shear * anchor.y())
        else:
            denominator = handle_local.x() - anchor.x()
            if abs(denominator) <= 1e-12:
                return None
            shear = (desired_local.y() - handle_local.y()) / denominator
            local_skew = LayerTransform(m12=shear, dy=-shear * anchor.x())
        candidate = compose_layer_mappings(local_skew, self._initial)
        return candidate if candidate is not None and candidate.is_invertible else None
