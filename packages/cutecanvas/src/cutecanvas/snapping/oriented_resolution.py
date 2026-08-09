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

"""Deterministic fixed-angle finite-edge snapping with hysteresis."""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF

from .edge_index import OrientedEdgeIndex
from .edge_model import OrientedEdge, OrientedEdgeKind, OrientedSnapGuide
from .model import SnapGrid

_PARALLEL_SINE_TOLERANCE = 1e-4


@dataclass(frozen=True, slots=True)
class OrientedSnapResult:
    """Return a resolved normal displacement and truthful finite guide."""

    distance: float
    guide: OrientedSnapGuide | None = None


@dataclass(frozen=True, slots=True)
class _OrientedLock:
    """Retain one stationary target during pointer jitter."""

    owner_id: str
    line_offset: float


class OrientedEdgeSnapResolver:
    """Resolve translations of one fixed-angle edge against frozen targets."""

    def __init__(
        self,
        source: OrientedEdge,
        targets: OrientedEdgeIndex,
        *,
        threshold_device_pixels: float,
        release_device_pixels: float,
        minimum_overlap_device_pixels: float = 1.0,
        grid: SnapGrid | None = None,
    ) -> None:
        """Capture immutable targets and device-pixel policy."""
        self._source = source
        self._targets = targets
        self._threshold = float(threshold_device_pixels)
        self._release = float(release_device_pixels)
        self._minimum_overlap = float(minimum_overlap_device_pixels)
        self._grid = grid
        self._lock: _OrientedLock | None = None

    def resolve(
        self,
        distance: float,
        *,
        scene_units_per_device_pixel: float,
        suppressed: bool = False,
    ) -> OrientedSnapResult:
        """Return the best reachable line offset without changing edge angle."""
        raw_distance = float(distance)
        scale = max(1e-9, float(scene_units_per_device_pixel))
        if suppressed:
            self._lock = None
            return OrientedSnapResult(raw_distance)
        moving = self._source.translated(raw_distance)
        release = self._release * scale
        locked = self._locked_candidate(moving, release)
        if locked is not None:
            correction = locked.line_offset - moving.line_offset
            return self._result(raw_distance + correction, locked)
        self._lock = None
        threshold = self._threshold * scale
        minimum_overlap = self._minimum_overlap * scale
        choices = tuple(
            candidate
            for candidate in self._candidates_near(moving, threshold)
            if candidate.owner_id != moving.owner_id
            and _parallel(moving, candidate)
            and _overlap(moving, candidate) >= minimum_overlap
            and abs(candidate.line_offset - moving.line_offset) <= threshold
        )
        if not choices:
            return OrientedSnapResult(raw_distance)
        target = min(
            choices,
            key=lambda candidate: (
                abs(candidate.line_offset - moving.line_offset),
                -candidate.priority,
                -_overlap(moving, candidate),
                candidate.owner_id,
                candidate.start.x(),
                candidate.start.y(),
            ),
        )
        self._lock = _OrientedLock(target.owner_id, target.line_offset)
        return self._result(
            raw_distance + target.line_offset - moving.line_offset,
            target,
        )

    def clear(self) -> None:
        """Release the current hysteresis target."""
        self._lock = None

    def _locked_candidate(
        self,
        moving: OrientedEdge,
        release: float,
    ) -> OrientedEdge | None:
        """Return the retained target while it remains geometrically valid."""
        lock = self._lock
        if lock is None:
            return None
        return next(
            (
                target
                for target in self._candidates_near(moving, release, locked=lock)
                if target.owner_id == lock.owner_id
                and math.isclose(
                    target.line_offset,
                    lock.line_offset,
                    rel_tol=1e-12,
                    abs_tol=1e-9,
                )
                and _parallel(moving, target)
                and abs(target.line_offset - moving.line_offset) <= release
            ),
            None,
        )

    def _candidates_near(
        self,
        moving: OrientedEdge,
        radius: float,
        *,
        locked: _OrientedLock | None = None,
    ) -> tuple[OrientedEdge, ...]:
        """Return indexed edges plus the reachable current grid line."""
        grid = self._grid_candidate(moving, locked=locked)
        return (
            self._targets.near_edge(moving, radius)
            if grid is None
            else (*self._targets.near_edge(moving, radius), grid)
        )

    def _grid_candidate(
        self,
        moving: OrientedEdge,
        *,
        locked: _OrientedLock | None,
    ) -> OrientedEdge | None:
        """Return one axis grid line compatible with the fixed edge angle."""
        grid = self._grid
        if grid is None:
            return None
        tangent = moving.tangent
        normal = moving.normal
        span = grid.guide_span
        locked_offset = (
            None
            if locked is None or not locked.owner_id.startswith("grid:oriented:")
            else locked.line_offset
        )
        if abs(tangent.x()) <= 1e-9:
            coordinate = (
                moving.midpoint.x()
                if locked_offset is None
                else locked_offset / normal.x()
            )
            if locked_offset is None:
                coordinate = (
                    grid.origin.x()
                    + round((coordinate - grid.origin.x()) / grid.spacing_x)
                    * grid.spacing_x
                )
            return OrientedEdge(
                "grid:oriented:x",
                QPointF(coordinate, span.top()),
                QPointF(coordinate, span.bottom()),
                span.center(),
                OrientedEdgeKind.GRID,
                grid.priority,
            )
        if abs(tangent.y()) <= 1e-9:
            coordinate = (
                moving.midpoint.y()
                if locked_offset is None
                else locked_offset / normal.y()
            )
            if locked_offset is None:
                coordinate = (
                    grid.origin.y()
                    + round((coordinate - grid.origin.y()) / grid.spacing_y)
                    * grid.spacing_y
                )
            return OrientedEdge(
                "grid:oriented:y",
                QPointF(span.left(), coordinate),
                QPointF(span.right(), coordinate),
                span.center(),
                OrientedEdgeKind.GRID,
                grid.priority,
            )
        return None

    def _result(
        self,
        resolved_distance: float,
        target: OrientedEdge,
    ) -> OrientedSnapResult:
        """Build a finite guide spanning both aligned edge projections."""
        source = self._source.translated(resolved_distance)
        tangent = source.tangent
        normal = source.normal
        start = min(source.projection_interval[0], target.projection_interval[0])
        end = max(source.projection_interval[1], target.projection_interval[1])
        offset = target.line_offset
        guide = OrientedSnapGuide(
            tangent * start + normal * offset,
            tangent * end + normal * offset,
            source.owner_id,
            target.owner_id,
        )
        return OrientedSnapResult(resolved_distance, guide)


def _parallel(first: OrientedEdge, second: OrientedEdge) -> bool:
    """Return whether canonical tangents describe the same fixed angle."""
    return (
        abs(
            first.tangent.x() * second.tangent.y()
            - first.tangent.y() * second.tangent.x()
        )
        <= _PARALLEL_SINE_TOLERANCE
    )


def _overlap(first: OrientedEdge, second: OrientedEdge) -> float:
    """Return shared projected length along the first canonical tangent."""
    tangent = first.tangent
    second_values = (
        QPointF.dotProduct(tangent, second.start),
        QPointF.dotProduct(tangent, second.end),
    )
    second_interval = min(second_values), max(second_values)
    first_interval = first.projection_interval
    return max(
        0.0,
        min(first_interval[1], second_interval[1])
        - max(first_interval[0], second_interval[0]),
    )


__all__ = ["OrientedEdgeSnapResolver", "OrientedSnapResult"]
