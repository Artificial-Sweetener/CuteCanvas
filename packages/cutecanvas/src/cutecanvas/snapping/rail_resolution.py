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

"""Deterministic snapping for a point constrained to one finite rail."""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF

from .edge_model import OrientedEdge, OrientedSnapGuide
from .model import SnapGrid

_PARALLEL_EPSILON = 1e-9


@dataclass(frozen=True, slots=True)
class RailSnapResult:
    """Return one rail-constrained point and optional truthful guide."""

    point: QPointF
    guide: OrientedSnapGuide | None = None

    def __post_init__(self) -> None:
        """Detach the mutable Qt point value."""
        object.__setattr__(self, "point", QPointF(self.point))


@dataclass(frozen=True, slots=True)
class _RailTarget:
    """Describe one frozen reachable intersection on the pivot rail."""

    point: QPointF
    owner_id: str
    priority: int
    guide_start: QPointF
    guide_end: QPointF


class RailSnapResolver:
    """Resolve one constrained pivot against frozen oriented targets."""

    def __init__(
        self,
        rail_start: QPointF,
        rail_end: QPointF,
        targets: tuple[OrientedEdge, ...],
        *,
        threshold_device_pixels: float,
        release_device_pixels: float,
        grid: SnapGrid | None = None,
    ) -> None:
        """Capture the finite rail, target intersections, and hysteresis policy."""
        self._start = QPointF(rail_start)
        self._end = QPointF(rail_end)
        delta = self._end - self._start
        self._length = math.hypot(delta.x(), delta.y())
        if self._length <= 1e-12:
            raise ValueError("snap rail must have positive length")
        self._direction = QPointF(delta.x() / self._length, delta.y() / self._length)
        self._targets = tuple(
            target
            for edge in targets
            if (target := self._intersection_target(edge)) is not None
        )
        self._threshold = float(threshold_device_pixels)
        self._release = float(release_device_pixels)
        self._grid = grid
        self._lock: _RailTarget | None = None

    def resolve(
        self,
        pointer: QPointF,
        *,
        scene_units_per_device_pixel: float,
        suppressed: bool = False,
    ) -> RailSnapResult:
        """Project and snap one pointer using device-pixel thresholds."""
        raw = self._project(pointer)
        scale = max(1e-9, float(scene_units_per_device_pixel))
        if suppressed:
            self._lock = None
            return RailSnapResult(raw)
        candidates = (*self._targets, *self._grid_targets(raw))
        if self._lock is not None:
            locked = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate.owner_id == self._lock.owner_id
                    and _distance(candidate.point, self._lock.point) <= 1e-8
                ),
                None,
            )
            if (
                locked is not None
                and _distance(raw, locked.point) <= self._release * scale
            ):
                return self._result(locked)
            self._lock = None
        threshold = self._threshold * scale
        reachable = tuple(
            candidate
            for candidate in candidates
            if _distance(raw, candidate.point) <= threshold
        )
        if not reachable:
            return RailSnapResult(raw)
        target = min(
            reachable,
            key=lambda candidate: (
                _distance(raw, candidate.point),
                -candidate.priority,
                candidate.owner_id,
                candidate.point.x(),
                candidate.point.y(),
            ),
        )
        self._lock = target
        return self._result(target)

    def clear(self) -> None:
        """Release the current hysteresis target."""
        self._lock = None

    def _project(self, point: QPointF) -> QPointF:
        """Project one point onto the complete finite rail."""
        distance = QPointF.dotProduct(QPointF(point) - self._start, self._direction)
        return self._start + self._direction * min(self._length, max(0.0, distance))

    def _intersection_target(self, edge: OrientedEdge) -> _RailTarget | None:
        """Return the finite line intersection between the rail and one edge."""
        rail = self._end - self._start
        target = edge.end - edge.start
        denominator = _cross(rail, target)
        if abs(denominator) <= _PARALLEL_EPSILON * self._length * edge.length:
            return None
        offset = edge.start - self._start
        rail_parameter = _cross(offset, target) / denominator
        edge_parameter = _cross(offset, rail) / denominator
        if not 0.0 <= rail_parameter <= 1.0 or not 0.0 <= edge_parameter <= 1.0:
            return None
        point = self._start + rail * rail_parameter
        return _RailTarget(
            point,
            edge.owner_id,
            edge.priority,
            edge.start,
            edge.end,
        )

    def _grid_targets(self, point: QPointF) -> tuple[_RailTarget, ...]:
        """Return nearest reachable horizontal and vertical grid crossings."""
        grid = self._grid
        if grid is None:
            return ()
        targets: list[_RailTarget] = []
        span = grid.guide_span
        if abs(self._direction.x()) > _PARALLEL_EPSILON:
            coordinate = (
                grid.origin.x()
                + round((point.x() - grid.origin.x()) / grid.spacing_x) * grid.spacing_x
            )
            target = self._point_at_x(coordinate)
            if target is not None:
                targets.append(
                    _RailTarget(
                        target,
                        f"grid:rail:x:{coordinate:.12g}",
                        grid.priority,
                        QPointF(coordinate, span.top()),
                        QPointF(coordinate, span.bottom()),
                    )
                )
        if abs(self._direction.y()) > _PARALLEL_EPSILON:
            coordinate = (
                grid.origin.y()
                + round((point.y() - grid.origin.y()) / grid.spacing_y) * grid.spacing_y
            )
            target = self._point_at_y(coordinate)
            if target is not None:
                targets.append(
                    _RailTarget(
                        target,
                        f"grid:rail:y:{coordinate:.12g}",
                        grid.priority,
                        QPointF(span.left(), coordinate),
                        QPointF(span.right(), coordinate),
                    )
                )
        return tuple(targets)

    def _point_at_x(self, coordinate: float) -> QPointF | None:
        """Return the rail point at one x coordinate when finite."""
        distance = (coordinate - self._start.x()) / self._direction.x()
        return (
            self._start + self._direction * distance
            if 0.0 <= distance <= self._length
            else None
        )

    def _point_at_y(self, coordinate: float) -> QPointF | None:
        """Return the rail point at one y coordinate when finite."""
        distance = (coordinate - self._start.y()) / self._direction.y()
        return (
            self._start + self._direction * distance
            if 0.0 <= distance <= self._length
            else None
        )

    @staticmethod
    def _result(target: _RailTarget) -> RailSnapResult:
        """Build presentation feedback for one applied target."""
        return RailSnapResult(
            target.point,
            OrientedSnapGuide(
                target.guide_start,
                target.guide_end,
                "shared-edge:pivot",
                target.owner_id,
            ),
        )


def _cross(first: QPointF, second: QPointF) -> float:
    """Return the scalar two-dimensional cross product."""
    return first.x() * second.y() - first.y() * second.x()


def _distance(first: QPointF, second: QPointF) -> float:
    """Return Euclidean distance between detached points."""
    return math.hypot(first.x() - second.x(), first.y() - second.y())


__all__ = ["RailSnapResolver", "RailSnapResult"]
