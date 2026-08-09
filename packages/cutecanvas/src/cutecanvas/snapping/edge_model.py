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

"""Immutable finite-edge geometry for oriented editor snapping."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from PySide6.QtCore import QPointF

from .model import SnapGuide

_EPSILON = 1e-12


class OrientedEdgeKind(str, Enum):
    """Identify the source domain of one oriented snap edge."""

    LAYER = "layer"
    CANVAS = "canvas"
    GUIDE = "guide"
    GRID = "grid"


@dataclass(frozen=True, slots=True)
class OrientedEdge:
    """Describe one finite straight feature in scene coordinates."""

    owner_id: str
    start: QPointF
    end: QPointF
    owner_center: QPointF
    kind: OrientedEdgeKind = OrientedEdgeKind.LAYER
    priority: int = 0

    def __post_init__(self) -> None:
        """Detach Qt geometry and reject degenerate or non-finite edges."""
        start = QPointF(self.start)
        end = QPointF(self.end)
        center = QPointF(self.owner_center)
        values = (
            start.x(),
            start.y(),
            end.x(),
            end.y(),
            center.x(),
            center.y(),
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("oriented edge geometry must be finite")
        if math.hypot(end.x() - start.x(), end.y() - start.y()) <= _EPSILON:
            raise ValueError("oriented edges must have positive length")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "owner_center", center)

    @property
    def length(self) -> float:
        """Return finite segment length in scene units."""
        return math.hypot(
            self.end.x() - self.start.x(),
            self.end.y() - self.start.y(),
        )

    @property
    def tangent(self) -> QPointF:
        """Return a canonical unit tangent independent of endpoint order."""
        delta = self.end - self.start
        length = self.length
        tangent = QPointF(delta.x() / length, delta.y() / length)
        if tangent.x() < -_EPSILON or (
            abs(tangent.x()) <= _EPSILON and tangent.y() < 0.0
        ):
            tangent = -tangent
        return tangent

    @property
    def normal(self) -> QPointF:
        """Return the canonical unit normal associated with ``tangent``."""
        tangent = self.tangent
        return QPointF(-tangent.y(), tangent.x())

    @property
    def line_offset(self) -> float:
        """Return signed origin distance along the canonical normal."""
        return QPointF.dotProduct(self.normal, self.start)

    @property
    def projection_interval(self) -> tuple[float, float]:
        """Return the ordered finite interval along the canonical tangent."""
        tangent = self.tangent
        values = (
            QPointF.dotProduct(tangent, self.start),
            QPointF.dotProduct(tangent, self.end),
        )
        return min(values), max(values)

    @property
    def midpoint(self) -> QPointF:
        """Return the detached segment midpoint."""
        return (self.start + self.end) * 0.5

    def distance_to_point(self, point: QPointF) -> float:
        """Return Euclidean distance from ``point`` to this finite segment."""
        segment = self.end - self.start
        length_squared = QPointF.dotProduct(segment, segment)
        projection = max(
            0.0,
            min(
                1.0,
                QPointF.dotProduct(QPointF(point) - self.start, segment)
                / length_squared,
            ),
        )
        closest = self.start + segment * projection
        return math.hypot(point.x() - closest.x(), point.y() - closest.y())

    def translated(self, distance: float) -> OrientedEdge:
        """Return this edge translated along its canonical normal."""
        delta = self.normal * float(distance)
        return OrientedEdge(
            self.owner_id,
            self.start + delta,
            self.end + delta,
            self.owner_center + delta,
            self.kind,
            self.priority,
        )


@dataclass(frozen=True, slots=True)
class OrientedSnapGuide:
    """Describe one finite scene-space Smart Guide segment."""

    start: QPointF
    end: QPointF
    source_owner_id: str
    target_owner_id: str

    def __post_init__(self) -> None:
        """Detach mutable Qt point storage."""
        object.__setattr__(self, "start", QPointF(self.start))
        object.__setattr__(self, "end", QPointF(self.end))


SnapGuideValue: TypeAlias = SnapGuide | OrientedSnapGuide


def quadrilateral_edges(
    owner_id: str,
    corners: tuple[QPointF, QPointF, QPointF, QPointF],
    *,
    kind: OrientedEdgeKind = OrientedEdgeKind.LAYER,
    priority: int = 0,
) -> tuple[OrientedEdge, OrientedEdge, OrientedEdge, OrientedEdge]:
    """Return four finite edges around an ordered affine quadrilateral."""
    edges = polygon_edges(
        owner_id,
        corners,
        kind=kind,
        priority=priority,
    )
    if len(edges) != 4:
        raise ValueError("quadrilateral corners must define four finite edges")
    return edges[0], edges[1], edges[2], edges[3]


def polygon_edges(
    owner_id: str,
    boundary: tuple[QPointF, ...],
    *,
    kind: OrientedEdgeKind = OrientedEdgeKind.LAYER,
    priority: int = 0,
) -> tuple[OrientedEdge, ...]:
    """Return the positive-length edges around one ordered polygon boundary."""
    if len(boundary) < 3:
        raise ValueError("polygon boundary must contain at least three points")
    points = _coalesced_points(boundary)
    if len(points) < 3:
        raise ValueError("polygon boundary must contain at least three finite edges")
    center = sum(points, QPointF()) * (1.0 / len(points))
    return tuple(
        OrientedEdge(
            owner_id,
            point,
            points[(index + 1) % len(points)],
            center,
            kind,
            priority,
        )
        for index, point in enumerate(points)
    )


def _coalesced_points(boundary: tuple[QPointF, ...]) -> tuple[QPointF, ...]:
    """Remove adjacent joined vertices before deriving edge geometry."""
    points: list[QPointF] = []
    for point in boundary:
        detached = QPointF(point)
        if (
            not points
            or math.hypot(
                detached.x() - points[-1].x(),
                detached.y() - points[-1].y(),
            )
            > _EPSILON
        ):
            points.append(detached)
    if (
        len(points) > 1
        and math.hypot(
            points[0].x() - points[-1].x(),
            points[0].y() - points[-1].y(),
        )
        <= _EPSILON
    ):
        points.pop()
    return tuple(points)


__all__ = [
    "OrientedEdge",
    "OrientedEdgeKind",
    "OrientedSnapGuide",
    "SnapGuideValue",
    "polygon_edges",
    "quadrilateral_edges",
]
