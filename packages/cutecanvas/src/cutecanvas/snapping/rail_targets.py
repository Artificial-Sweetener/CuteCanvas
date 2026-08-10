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

"""Frozen orientation and continuity targets for finite-rail snapping."""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF

from .edge_model import OrientedEdge

_INTERSECTION_EPSILON = 1e-9
_LINE_COINCIDENCE_EPSILON = 1e-7


@dataclass(frozen=True, slots=True)
class RailSnapTarget:
    """Describe one reachable rail point and its truthful guide geometry."""

    point: QPointF
    owner_id: str
    priority: int
    guide_start: QPointF
    guide_end: QPointF

    def __post_init__(self) -> None:
        """Detach mutable Qt point values."""
        for name in ("point", "guide_start", "guide_end"):
            object.__setattr__(self, name, QPointF(getattr(self, name)))


def alignment_targets(
    rail_start: QPointF,
    rail_end: QPointF,
    fixed_point: QPointF,
    edges: tuple[OrientedEdge, ...],
) -> tuple[RailSnapTarget, ...]:
    """Return exact perfect-angle and continuous-edge points on one rail."""
    targets = [
        *(
            _orientation_target(rail_start, rail_end, fixed_point, *value)
            for value in _ORIENTATIONS
        ),
        *(
            target
            for edge in edges
            if (
                target := _continuity_target(
                    rail_start,
                    rail_end,
                    fixed_point,
                    edge,
                )
            )
            is not None
        ),
    ]
    return tuple(target for target in targets if target is not None)


_ORIENTATIONS = (
    (QPointF(1.0, 0.0), "orientation:horizontal"),
    (QPointF(1.0, 1.0), "orientation:45"),
    (QPointF(0.0, 1.0), "orientation:vertical"),
    (QPointF(1.0, -1.0), "orientation:45"),
)


def _orientation_target(
    rail_start: QPointF,
    rail_end: QPointF,
    fixed_point: QPointF,
    direction: QPointF,
    owner_id: str,
) -> RailSnapTarget | None:
    """Return the rail point producing one exact undirected orientation."""
    point = _line_intersection(rail_start, rail_end, fixed_point, direction)
    if point is None or _distance(point, fixed_point) <= _INTERSECTION_EPSILON:
        return None
    return RailSnapTarget(point, owner_id, 0, fixed_point, point)


def _continuity_target(
    rail_start: QPointF,
    rail_end: QPointF,
    fixed_point: QPointF,
    edge: OrientedEdge,
) -> RailSnapTarget | None:
    """Return a rail point making the moved seam continuous with ``edge``."""
    relative = fixed_point - edge.start
    tangent = edge.tangent
    distance = abs(_cross(relative, tangent))
    if distance > _LINE_COINCIDENCE_EPSILON:
        return None
    point = _line_intersection(rail_start, rail_end, edge.start, tangent)
    if point is None or _distance(point, fixed_point) <= _INTERSECTION_EPSILON:
        return None
    seam_interval = sorted(
        QPointF.dotProduct(tangent, value) for value in (fixed_point, point)
    )
    edge_interval = edge.projection_interval
    gap = max(
        edge_interval[0] - seam_interval[1],
        seam_interval[0] - edge_interval[1],
        0.0,
    )
    if gap > _LINE_COINCIDENCE_EPSILON:
        return None
    guide_points = (fixed_point, point, edge.start, edge.end)
    ordered = sorted(
        guide_points,
        key=lambda value: QPointF.dotProduct(tangent, value),
    )
    return RailSnapTarget(
        point,
        edge.owner_id,
        edge.priority,
        ordered[0],
        ordered[-1],
    )


def _line_intersection(
    rail_start: QPointF,
    rail_end: QPointF,
    line_point: QPointF,
    line_direction: QPointF,
) -> QPointF | None:
    """Intersect one infinite line with one finite rail segment."""
    rail = rail_end - rail_start
    denominator = _cross(rail, line_direction)
    scale = math.hypot(rail.x(), rail.y()) * math.hypot(
        line_direction.x(),
        line_direction.y(),
    )
    if abs(denominator) <= _INTERSECTION_EPSILON * scale:
        return None
    parameter = _cross(line_point - rail_start, line_direction) / denominator
    if not 0.0 <= parameter <= 1.0:
        return None
    return rail_start + rail * parameter


def _cross(first: QPointF, second: QPointF) -> float:
    """Return the scalar two-dimensional cross product."""
    return first.x() * second.y() - first.y() * second.x()


def _distance(first: QPointF, second: QPointF) -> float:
    """Return Euclidean distance between two detached points."""
    return math.hypot(first.x() - second.x(), first.y() - second.y())


__all__ = ["RailSnapTarget", "alignment_targets"]
