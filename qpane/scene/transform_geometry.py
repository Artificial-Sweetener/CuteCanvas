#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Exact affine geometry for interactive layer transform handles."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QPointF

from .affine import LayerTransform


class TransformHandle(str, Enum):
    """Identify one Photoshop-style transform-box edit point."""

    TOP_LEFT = "top-left"
    TOP = "top"
    TOP_RIGHT = "top-right"
    RIGHT = "right"
    BOTTOM_RIGHT = "bottom-right"
    BOTTOM = "bottom"
    BOTTOM_LEFT = "bottom-left"
    LEFT = "left"


class TransformOperationKind(str, Enum):
    """Describe the affine operation selected by transform hit testing."""

    MOVE = "move"
    SCALE = "scale"
    ROTATE = "rotate"
    SKEW = "skew"


@dataclass(frozen=True, slots=True)
class TransformOperation:
    """Pair one transform operation with its optional box handle."""

    kind: TransformOperationKind
    handle: TransformHandle | None = None

    def __post_init__(self) -> None:
        """Require handles exactly for scale and skew operations."""
        requires_handle = self.kind in {
            TransformOperationKind.SCALE,
            TransformOperationKind.SKEW,
        }
        if requires_handle != (self.handle is not None):
            raise ValueError("scale and skew operations require one transform handle")


@dataclass(frozen=True, slots=True)
class TransformModifiers:
    """Describe the constraint policy active for one pointer update."""

    proportional: bool = True
    about_center: bool = False
    snap_rotation: bool = False


@dataclass(frozen=True, slots=True)
class TransformLocalBounds:
    """Store positive source-local content bounds without mutable Qt state."""

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        """Reject unusable transform target geometry."""
        values = (self.x, self.y, self.width, self.height)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("transform bounds must be finite")
        if self.width <= 0.0 or self.height <= 0.0:
            raise ValueError("transform bounds must have positive dimensions")

    @property
    def center(self) -> QPointF:
        """Return the detached local center point."""
        return QPointF(self.x + self.width * 0.5, self.y + self.height * 0.5)

    def point(self, handle: TransformHandle) -> QPointF:
        """Return the local corner or side midpoint for ``handle``."""
        left = self.x
        center_x = self.x + self.width * 0.5
        right = self.x + self.width
        top = self.y
        center_y = self.y + self.height * 0.5
        bottom = self.y + self.height
        return {
            TransformHandle.TOP_LEFT: QPointF(left, top),
            TransformHandle.TOP: QPointF(center_x, top),
            TransformHandle.TOP_RIGHT: QPointF(right, top),
            TransformHandle.RIGHT: QPointF(right, center_y),
            TransformHandle.BOTTOM_RIGHT: QPointF(right, bottom),
            TransformHandle.BOTTOM: QPointF(center_x, bottom),
            TransformHandle.BOTTOM_LEFT: QPointF(left, bottom),
            TransformHandle.LEFT: QPointF(left, center_y),
        }[handle]

    def opposite(self, handle: TransformHandle) -> QPointF:
        """Return the fixed opposite point for one scale handle."""
        opposite = {
            TransformHandle.TOP_LEFT: TransformHandle.BOTTOM_RIGHT,
            TransformHandle.TOP: TransformHandle.BOTTOM,
            TransformHandle.TOP_RIGHT: TransformHandle.BOTTOM_LEFT,
            TransformHandle.RIGHT: TransformHandle.LEFT,
            TransformHandle.BOTTOM_RIGHT: TransformHandle.TOP_LEFT,
            TransformHandle.BOTTOM: TransformHandle.TOP,
            TransformHandle.BOTTOM_LEFT: TransformHandle.TOP_RIGHT,
            TransformHandle.LEFT: TransformHandle.RIGHT,
        }
        return self.point(opposite[handle])


class AffineTransformGeometry:
    """Derive exact affine previews from one durable transform-box base."""

    def __init__(
        self,
        bounds: TransformLocalBounds,
        initial_transform: LayerTransform,
    ) -> None:
        """Bind source-local bounds and one invertible durable transform."""
        if not initial_transform.is_invertible:
            raise ValueError("initial transform must be invertible")
        self._bounds = bounds
        self._initial = initial_transform

    @property
    def bounds(self) -> TransformLocalBounds:
        """Return immutable source-local target bounds."""
        return self._bounds

    @property
    def initial_transform(self) -> LayerTransform:
        """Return the immutable durable transform base."""
        return self._initial

    def scene_point(self, handle: TransformHandle) -> QPointF:
        """Return one handle center in scene coordinates."""
        return self._initial.map_point(self._bounds.point(handle))

    def scene_center(self) -> QPointF:
        """Return the transform reference center in scene coordinates."""
        return self._initial.map_point(self._bounds.center)

    def transform_for_drag(
        self,
        operation: TransformOperation,
        pointer_origin: QPointF,
        pointer_position: QPointF,
        modifiers: TransformModifiers,
    ) -> LayerTransform | None:
        """Return an exact preview transform for one pointer displacement."""
        if operation.kind is TransformOperationKind.MOVE:
            delta = pointer_position - pointer_origin
            return self._initial.translated(delta.x(), delta.y())
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
    ) -> LayerTransform | None:
        """Scale local geometry about its opposite handle or center."""
        anchor = (
            self._bounds.center
            if modifiers.about_center
            else self._bounds.opposite(handle)
        )
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
            anchor_scene = self._initial.map_point(anchor)
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
        candidate = local_scale.followed_by(self._initial)
        return candidate if candidate.is_invertible else None

    def _rotation(
        self,
        pointer_origin: QPointF,
        pointer_position: QPointF,
        modifiers: TransformModifiers,
    ) -> LayerTransform | None:
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
        candidate = self._initial.followed_by(rotation)
        return candidate if candidate.is_invertible else None

    def _skew(
        self,
        handle: TransformHandle,
        pointer_origin: QPointF,
        pointer_position: QPointF,
        modifiers: TransformModifiers,
    ) -> LayerTransform | None:
        """Skew one side in local space about the opposite side or center."""
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
        candidate = local_skew.followed_by(self._initial)
        return candidate if candidate.is_invertible else None
