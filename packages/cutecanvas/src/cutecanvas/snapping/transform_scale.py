#    CuteCanvas - High-performance layered image editor
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

"""Constrained affine scale resolution against frozen snap targets."""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF
from qpane.sdk.scene import (
    AffineTransformGeometry,
    LayerMapping,
    TransformHandle,
    TransformModifiers,
    TransformOperation,
    TransformOperationKind,
)

from cutecanvas.scene.transform_session import LayerTransformBoxState

from .axis_resolution import AxisSnapLock, AxisSnapResolver, build_candidate_index
from .candidates import SnapTargetSnapshot
from .configuration import SnapConfiguration
from .edge_candidates import OrientedTargetSnapshot
from .edge_model import SnapGuideValue
from .model import SnapAxis, SnapFeatureKind, SnapGuide
from .transform_oriented_scale import create_transform_oriented_scale_snap

_CORNER_HANDLES = {
    TransformHandle.TOP_LEFT,
    TransformHandle.TOP_RIGHT,
    TransformHandle.BOTTOM_RIGHT,
    TransformHandle.BOTTOM_LEFT,
}
_FRAME_CORNERS = (
    TransformHandle.TOP_LEFT,
    TransformHandle.TOP_RIGHT,
    TransformHandle.BOTTOM_RIGHT,
    TransformHandle.BOTTOM_LEFT,
)


@dataclass(frozen=True, slots=True)
class TransformSnapResult:
    """Return a resolved scene pointer and truthful Smart Guides."""

    scene_point: QPointF
    guides: tuple[SnapGuideValue, ...] = ()

    def __post_init__(self) -> None:
        """Detach mutable Qt point storage from the session."""
        object.__setattr__(self, "scene_point", QPointF(self.scene_point))


class TransformScaleSnapSession:
    """Resolve one scale handle against immutable scene-coordinate targets."""

    def __init__(
        self,
        box: LayerTransformBoxState,
        operation: TransformOperation,
        origin: QPointF,
        targets: SnapTargetSnapshot,
        configuration: SnapConfiguration,
        *,
        oriented_targets: OrientedTargetSnapshot | None = None,
        scene_units_per_device_pixel: float = 1.0,
    ) -> None:
        """Capture affine geometry, candidates, thresholds, and pointer origin."""
        if (
            operation.kind is not TransformOperationKind.SCALE
            or operation.handle is None
        ):
            raise ValueError("transform scale snapping requires one scale handle")
        policy = configuration.policy
        candidate_index = build_candidate_index(targets.candidates)
        kinds = _handle_feature_kinds(operation.handle)
        self._box = box
        self._operation = operation
        self._origin = QPointF(origin)
        self._geometry = AffineTransformGeometry(box.bounds, box.transform)
        self._initial_handle = self._geometry.scene_point(operation.handle)
        self._oriented = create_transform_oriented_scale_snap(
            box,
            operation,
            origin,
            oriented_targets,
            threshold_device_pixels=policy.threshold_device_pixels,
            release_device_pixels=policy.release_device_pixels,
            scene_units_per_device_pixel=scene_units_per_device_pixel,
        )
        self._x = AxisSnapResolver(
            SnapAxis.X,
            candidate_index.for_axis(SnapAxis.X),
            threshold_device_pixels=policy.threshold_device_pixels,
            release_device_pixels=policy.release_device_pixels,
            grid=targets.grid,
            relationship_rank=_scale_relationship_rank,
            moving_kinds=(kinds[0],),
        )
        self._y = AxisSnapResolver(
            SnapAxis.Y,
            candidate_index.for_axis(SnapAxis.Y),
            threshold_device_pixels=policy.threshold_device_pixels,
            release_device_pixels=policy.release_device_pixels,
            grid=targets.grid,
            relationship_rank=_scale_relationship_rank,
            moving_kinds=(kinds[1],),
        )
        self._kinds = kinds

    def resolve(
        self,
        scene_point: QPointF,
        modifiers: TransformModifiers,
        *,
        scene_units_per_device_pixel: float,
        suppressed: bool = False,
    ) -> TransformSnapResult:
        """Return the pointer that produces an exactly snapped affine handle."""
        raw_point = QPointF(scene_point)
        if suppressed:
            self._x.clear()
            self._y.clear()
            if self._oriented is not None:
                self._oriented.clear()
            return TransformSnapResult(raw_point)
        raw_transform = self._geometry.transform_for_drag(
            self._operation,
            self._origin,
            raw_point,
            modifiers,
        )
        handle = self._operation.handle
        if raw_transform is None or handle is None:
            return TransformSnapResult(raw_point)
        scale = max(1e-9, float(scene_units_per_device_pixel))
        raw_handle = raw_transform.map_point(self._box.bounds.point(handle))
        oriented = (
            None
            if self._oriented is None
            else self._oriented.resolve(
                raw_handle,
                modifiers,
                scene_units_per_device_pixel=scale,
            )
        )
        if oriented is not None:
            return TransformSnapResult(oriented[0], (oriented[1],))
        x = self._x.resolve(
            raw_handle.x(),
            ((self._kinds[0], raw_handle.x()),),
            scene_units_per_device_pixel=scale,
        )
        y = self._y.resolve(
            raw_handle.y(),
            ((self._kinds[1], raw_handle.y()),),
            scene_units_per_device_pixel=scale,
        )
        desired_handle, locks = self._resolved_handle(
            raw_handle,
            x.lock,
            y.lock,
            QPointF(x.value, y.value),
            modifiers,
        )
        resolved_pointer = self._origin + desired_handle - self._initial_handle
        resolved_transform = self._geometry.transform_for_drag(
            self._operation,
            self._origin,
            resolved_pointer,
            modifiers,
        )
        if resolved_transform is None:
            return TransformSnapResult(raw_point)
        return TransformSnapResult(
            resolved_pointer,
            self._guides(locks, resolved_transform),
        )

    def _resolved_handle(
        self,
        raw_handle: QPointF,
        x_lock: AxisSnapLock | None,
        y_lock: AxisSnapLock | None,
        independent: QPointF,
        modifiers: TransformModifiers,
    ) -> tuple[QPointF, tuple[tuple[SnapAxis, AxisSnapLock], ...]]:
        """Reconcile independent axis locks with the handle's scale freedom."""
        handle = self._operation.handle
        if handle is None:
            return raw_handle, ()
        if handle in _CORNER_HANDLES and not modifiers.proportional:
            locks = tuple(
                (axis, lock)
                for axis, lock in (
                    (SnapAxis.X, x_lock),
                    (SnapAxis.Y, y_lock),
                )
                if lock is not None
            )
            return independent, locks
        anchor_local = (
            self._box.bounds.center
            if modifiers.about_center
            else self._box.bounds.opposite(handle)
        )
        anchor = self._box.transform.map_point(anchor_local)
        vector = self._initial_handle - anchor
        choices = self._constraint_choices(raw_handle, vector, x_lock, y_lock)
        if not choices:
            self._x.clear()
            self._y.clear()
            return raw_handle, ()
        if len(choices) == 2 and math.isclose(
            choices[0][2], choices[1][2], rel_tol=1e-9, abs_tol=1e-9
        ):
            factor = (choices[0][2] + choices[1][2]) * 0.5
            return anchor + vector * factor, tuple(
                (axis, lock) for _correction, axis, _factor, lock in choices
            )
        _correction, kept_axis, factor, kept_lock = min(
            choices,
            key=lambda choice: (choice[0], 0 if choice[1] is SnapAxis.X else 1),
        )
        if kept_axis is SnapAxis.X:
            self._y.clear()
        else:
            self._x.clear()
        return anchor + vector * factor, ((kept_axis, kept_lock),)

    def _constraint_choices(
        self,
        raw_handle: QPointF,
        vector: QPointF,
        x_lock: AxisSnapLock | None,
        y_lock: AxisSnapLock | None,
    ) -> tuple[tuple[float, SnapAxis, float, AxisSnapLock], ...]:
        """Return reachable one-dimensional factors for acquired axis locks."""
        choices: list[tuple[float, SnapAxis, float, AxisSnapLock]] = []
        anchor = self._initial_handle - vector
        for axis, component, raw_value, lock in (
            (SnapAxis.X, vector.x(), raw_handle.x(), x_lock),
            (SnapAxis.Y, vector.y(), raw_handle.y(), y_lock),
        ):
            if lock is None or abs(component) <= 1e-12:
                continue
            target = lock.candidate.position
            anchor_value = anchor.x() if axis is SnapAxis.X else anchor.y()
            choices.append(
                (
                    abs(target - raw_value),
                    axis,
                    (target - anchor_value) / component,
                    lock,
                )
            )
        return tuple(choices)

    def _guides(
        self,
        locks: tuple[tuple[SnapAxis, AxisSnapLock], ...],
        transform: LayerMapping,
    ) -> tuple[SnapGuide, ...]:
        """Build guides spanning the resolved frame and stationary target."""
        corners = tuple(
            transform.map_point(self._box.bounds.point(handle))
            for handle in _FRAME_CORNERS
        )
        return tuple(
            _scale_guide(str(self._box.layer_id), axis, lock, corners)
            for axis, lock in locks
        )


def _handle_feature_kinds(
    handle: TransformHandle,
) -> tuple[SnapFeatureKind, SnapFeatureKind]:
    """Return the horizontal and vertical frame features moved by a handle."""
    horizontal = {
        TransformHandle.TOP_LEFT: SnapFeatureKind.START,
        TransformHandle.TOP: SnapFeatureKind.CENTER,
        TransformHandle.TOP_RIGHT: SnapFeatureKind.END,
        TransformHandle.RIGHT: SnapFeatureKind.END,
        TransformHandle.BOTTOM_RIGHT: SnapFeatureKind.END,
        TransformHandle.BOTTOM: SnapFeatureKind.CENTER,
        TransformHandle.BOTTOM_LEFT: SnapFeatureKind.START,
        TransformHandle.LEFT: SnapFeatureKind.START,
    }
    vertical = {
        TransformHandle.TOP_LEFT: SnapFeatureKind.START,
        TransformHandle.TOP: SnapFeatureKind.START,
        TransformHandle.TOP_RIGHT: SnapFeatureKind.START,
        TransformHandle.RIGHT: SnapFeatureKind.CENTER,
        TransformHandle.BOTTOM_RIGHT: SnapFeatureKind.END,
        TransformHandle.BOTTOM: SnapFeatureKind.END,
        TransformHandle.BOTTOM_LEFT: SnapFeatureKind.END,
        TransformHandle.LEFT: SnapFeatureKind.CENTER,
    }
    return horizontal[handle], vertical[handle]


def _scale_relationship_rank(
    moving: SnapFeatureKind,
    target: SnapFeatureKind,
    _accepts_cross_feature: bool,
) -> int | None:
    """Rank exact edge relationships before centers and authored lines."""
    if target in {SnapFeatureKind.GUIDE, SnapFeatureKind.GRID}:
        return 0
    if moving is target:
        return 0
    if {moving, target} == {SnapFeatureKind.START, SnapFeatureKind.END}:
        return 1
    if SnapFeatureKind.CENTER in {moving, target}:
        return 2
    return None


def _scale_guide(
    source_owner_id: str,
    axis: SnapAxis,
    lock: AxisSnapLock,
    corners: tuple[QPointF, ...],
) -> SnapGuide:
    """Return a guide spanning the resolved affine frame and its target."""
    source_values = (
        tuple(point.y() for point in corners)
        if axis is SnapAxis.X
        else tuple(point.x() for point in corners)
    )
    candidate = lock.candidate
    return SnapGuide(
        axis,
        candidate.position,
        min(*source_values, candidate.span_start),
        max(*source_values, candidate.span_end),
        source_owner_id,
        candidate.owner_id,
    )


__all__ = ["TransformScaleSnapSession", "TransformSnapResult"]
