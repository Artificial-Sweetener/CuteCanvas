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

"""Frozen geometry and snap resolution for one shared-edge gesture."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from PySide6.QtCore import QPointF
from qpane.sdk.scene import LayerMapping

from cutecanvas.snapping.edge_candidates import OrientedTargetSnapshot
from cutecanvas.snapping.edge_index import OrientedEdgeIndex
from cutecanvas.snapping.edge_model import SnapGuideValue
from cutecanvas.snapping.oriented_resolution import OrientedEdgeSnapResolver
from cutecanvas.snapping.rail_resolution import RailSnapResolver

from .shared_edge_geometry import SharedEdgeSeam
from .shared_edge_pivot import SharedEdgeHandle, SharedEdgePivot


@dataclass(frozen=True, slots=True)
class SharedEdgeGestureUpdate:
    """Return every exact participant mapping, seam endpoints, and truthful guides."""

    values: tuple[tuple[uuid.UUID, LayerMapping], ...]
    points: tuple[QPointF, QPointF]
    guides: tuple[SnapGuideValue, ...] = ()

    def __post_init__(self) -> None:
        """Detach mutable endpoint values."""
        object.__setattr__(
            self,
            "points",
            (QPointF(self.points[0]), QPointF(self.points[1])),
        )


class SharedEdgeGestureSession:
    """Resolve one frozen midpoint or endpoint gesture without editor state."""

    def __init__(
        self,
        *,
        seam: SharedEdgeSeam,
        handle: SharedEdgeHandle,
        pivot: SharedEdgePivot | None,
        origin: QPointF,
        targets: OrientedTargetSnapshot | None,
        scene_units_per_device_pixel: float,
    ) -> None:
        """Capture immutable source geometry and stationary snap targets."""
        if handle is not SharedEdgeHandle.MIDDLE and pivot is None:
            raise ValueError("endpoint gestures require a valid pivot constraint")
        if handle is SharedEdgeHandle.MIDDLE and not seam.parallel_translation_enabled:
            raise ValueError("angled shared edges do not expose whole-edge translation")
        self.seam = seam
        self.handle = handle
        self._pivot = pivot
        self._origin = QPointF(origin)
        self._points = (QPointF(seam.start), QPointF(seam.end))
        valid_targets = targets is not None and targets.scene_id == seam.scene_id
        scale = max(1e-9, float(scene_units_per_device_pixel))
        self._parallel_snap = (
            OrientedEdgeSnapResolver(
                seam.edge,
                OrientedEdgeIndex.build(
                    targets.edges,
                    scene_units_per_device_pixel=scale,
                ),
                threshold_device_pixels=6.0,
                release_device_pixels=9.0,
                grid=targets.grid,
            )
            if handle is SharedEdgeHandle.MIDDLE
            and valid_targets
            and targets is not None
            else None
        )
        self._rail_snap = (
            RailSnapResolver(
                pivot.rail_start,
                pivot.rail_end,
                targets.edges,
                threshold_device_pixels=6.0,
                release_device_pixels=9.0,
                grid=targets.grid,
            )
            if pivot is not None and valid_targets and targets is not None
            else None
        )

    @property
    def points(self) -> tuple[QPointF, QPointF]:
        """Return the latest resolved seam endpoints."""
        return QPointF(self._points[0]), QPointF(self._points[1])

    def resolve(
        self,
        scene_point: QPointF,
        *,
        scene_units_per_device_pixel: float,
        suppressed: bool,
    ) -> SharedEdgeGestureUpdate | None:
        """Resolve one pointer sample from the frozen gesture geometry."""
        scale = max(1e-9, float(scene_units_per_device_pixel))
        if self.handle is SharedEdgeHandle.MIDDLE:
            update = self._resolve_parallel(scene_point, scale, suppressed)
        else:
            update = self._resolve_pivot(scene_point, scale, suppressed)
        if update is not None:
            self._points = update.points
        return update

    def clear(self) -> None:
        """Release both snap hysteresis locks."""
        if self._parallel_snap is not None:
            self._parallel_snap.clear()
        if self._rail_snap is not None:
            self._rail_snap.clear()

    def _resolve_parallel(
        self,
        scene_point: QPointF,
        scale: float,
        suppressed: bool,
    ) -> SharedEdgeGestureUpdate:
        """Resolve one normal translation while keeping the seam parallel."""
        raw_distance = QPointF.dotProduct(
            self.seam.edge.normal,
            QPointF(scene_point) - self._origin,
        )
        result = (
            None
            if self._parallel_snap is None
            else self._parallel_snap.resolve(
                raw_distance,
                scene_units_per_device_pixel=scale,
                suppressed=suppressed,
            )
        )
        resolved = raw_distance if result is None else result.distance
        translation = self.seam.translation_for_distance(
            resolved,
            minimum_thickness=2.0 * scale,
        )
        distance = translation.distance
        displacement = self.seam.edge.normal * distance
        guides = (
            (result.guide,)
            if result is not None and result.guide is not None and distance == resolved
            else ()
        )
        return SharedEdgeGestureUpdate(
            translation.mappings,
            (self.seam.start + displacement, self.seam.end + displacement),
            guides,
        )

    def _resolve_pivot(
        self,
        scene_point: QPointF,
        scale: float,
        suppressed: bool,
    ) -> SharedEdgeGestureUpdate | None:
        """Resolve one endpoint along its common finite participant rail."""
        pivot = self._pivot
        if pivot is None:
            return None
        result = (
            None
            if self._rail_snap is None
            else self._rail_snap.resolve(
                scene_point,
                scene_units_per_device_pixel=scale,
                suppressed=suppressed,
            )
        )
        resolved = scene_point if result is None else result.point
        target = pivot.constrained_point(
            resolved,
            endpoint_join_span=6.0 * scale,
        )
        try:
            values = pivot.mappings_for_point(target)
        except ValueError:
            return None
        guides = (
            (result.guide,)
            if result is not None
            and result.guide is not None
            and _point_distance(target, result.point) <= 1e-9
            else ()
        )
        points = (
            (target, self.seam.end)
            if self.handle is SharedEdgeHandle.START
            else (self.seam.start, target)
        )
        return SharedEdgeGestureUpdate(values, points, guides)


def _point_distance(first: QPointF, second: QPointF) -> float:
    """Return Euclidean scene distance between two points."""
    delta = first - second
    return QPointF.dotProduct(delta, delta) ** 0.5


__all__ = ["SharedEdgeGestureSession", "SharedEdgeGestureUpdate"]
