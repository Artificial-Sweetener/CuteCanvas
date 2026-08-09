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

"""Canonical boundary topology for one shared-edge participant."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass

from PySide6.QtCore import QPointF
from qpane.sdk.scene import LayerMapping


@dataclass(frozen=True, slots=True)
class SharedEdgeParticipant:
    """Capture one layer's immutable mapping and shared boundary topology."""

    layer_id: uuid.UUID
    initial_mapping: LayerMapping
    source_boundary: tuple[QPointF, ...]
    scene_boundary: tuple[QPointF, ...]
    seam_indexes: tuple[int, int]
    translation_indexes: tuple[int, ...]
    interior_side: int

    def __post_init__(self) -> None:
        """Detach participant geometry and validate its boundary indexes."""
        object.__setattr__(
            self,
            "source_boundary",
            tuple(QPointF(point) for point in self.source_boundary),
        )
        object.__setattr__(
            self,
            "scene_boundary",
            tuple(QPointF(point) for point in self.scene_boundary),
        )
        if len(set(self.seam_indexes)) != 2 or any(
            not 0 <= index < len(self.scene_boundary) for index in self.seam_indexes
        ):
            raise ValueError("shared-edge participant requires two seam vertices")
        translation_indexes = tuple(dict.fromkeys(self.translation_indexes))
        if not set(self.seam_indexes).issubset(translation_indexes) or any(
            not 0 <= index < len(self.scene_boundary) for index in translation_indexes
        ):
            raise ValueError("shared-edge translation vertices must include the seam")
        object.__setattr__(self, "translation_indexes", translation_indexes)
        if self.interior_side not in {-1, 1}:
            raise ValueError("shared-edge participant side must be -1 or 1")


def shared_boundary_with_points(
    boundary: tuple[QPointF, ...],
    additions: tuple[QPointF, ...],
    tolerance: float,
) -> tuple[QPointF, ...]:
    """Insert seam endpoints into their containing ordered boundary edges."""
    points = _coalesced_boundary(boundary, tolerance)
    if len(points) < 3:
        raise ValueError("shared-edge participant boundary must be polygonal")
    result: list[QPointF] = []
    for index, start in enumerate(points):
        end = points[(index + 1) % len(points)]
        result.append(start)
        interior = sorted(
            (
                (_segment_parameter(point, start, end), point)
                for point in additions
                if _point_on_segment(point, start, end, tolerance)
                and _point_distance(point, start) > tolerance
                and _point_distance(point, end) > tolerance
            ),
            key=lambda value: value[0],
        )
        result.extend(QPointF(point) for _parameter, point in interior)
    return tuple(result)


def inverse_shared_boundary(
    mapping: LayerMapping,
    boundary: tuple[QPointF, ...],
) -> tuple[QPointF, ...] | None:
    """Resolve scene boundary vertices back into authoritative local space."""
    points = tuple(mapping.inverse_map(point) for point in boundary)
    if any(point is None for point in points):
        return None
    return tuple(QPointF(point) for point in points if point is not None)


def shared_endpoint_indexes(
    boundary: tuple[QPointF, ...],
    start: QPointF,
    end: QPointF,
    tolerance: float,
) -> tuple[int, int]:
    """Return the unique boundary indexes of both inserted seam endpoints."""
    indexes: list[int] = []
    for endpoint in (start, end):
        matches = tuple(
            index
            for index, point in enumerate(boundary)
            if _point_distance(point, endpoint) <= tolerance
        )
        if len(matches) != 1:
            raise ValueError("shared-edge endpoint must identify one boundary vertex")
        indexes.append(matches[0])
    return indexes[0], indexes[1]


def shared_translation_indexes(
    boundary: tuple[QPointF, ...],
    seam_indexes: tuple[int, int],
    tolerance: float,
) -> tuple[int, ...]:
    """Include each contiguous boundary vertex extending the straight seam."""
    first_index, second_index = seam_indexes
    size = len(boundary)
    seam_start = boundary[first_index]
    seam_end = boundary[second_index]
    on_line = {
        index
        for index, point in enumerate(boundary)
        if _point_on_line(point, seam_start, seam_end, tolerance)
    }
    moving = {first_index}
    pending = [first_index]
    while pending:
        index = pending.pop()
        for candidate in ((index - 1) % size, (index + 1) % size):
            if candidate in on_line and candidate not in moving:
                moving.add(candidate)
                pending.append(candidate)
    if second_index not in moving:
        raise ValueError("shared-edge endpoints must share one boundary chain")
    return tuple(sorted(moving))


def _coalesced_boundary(
    boundary: tuple[QPointF, ...],
    tolerance: float,
) -> tuple[QPointF, ...]:
    """Remove adjacent joined vertices while preserving polygon order."""
    points: list[QPointF] = []
    for point in boundary:
        detached = QPointF(point)
        if not points or _point_distance(points[-1], detached) > tolerance:
            points.append(detached)
    if len(points) > 1 and _point_distance(points[0], points[-1]) <= tolerance:
        points.pop()
    return tuple(points)


def _point_on_line(
    point: QPointF,
    start: QPointF,
    end: QPointF,
    tolerance: float,
) -> bool:
    """Return whether one point lies on an infinite line within tolerance."""
    edge = end - start
    relative = point - start
    length = math.hypot(edge.x(), edge.y())
    if length <= tolerance:
        return False
    cross = edge.x() * relative.y() - edge.y() * relative.x()
    return abs(cross) <= tolerance * max(1.0, length)


def _point_on_segment(
    point: QPointF,
    start: QPointF,
    end: QPointF,
    tolerance: float,
) -> bool:
    """Return whether one point lies on a finite boundary segment."""
    edge = end - start
    relative = point - start
    cross = edge.x() * relative.y() - edge.y() * relative.x()
    scale = max(1.0, math.hypot(edge.x(), edge.y()))
    if abs(cross) > tolerance * scale:
        return False
    parameter = _segment_parameter(point, start, end)
    parameter_tolerance = tolerance / scale
    return -parameter_tolerance <= parameter <= 1.0 + parameter_tolerance


def _segment_parameter(point: QPointF, start: QPointF, end: QPointF) -> float:
    """Return one point's scalar projection along a nonzero segment."""
    edge = end - start
    return QPointF.dotProduct(point - start, edge) / QPointF.dotProduct(edge, edge)


def _point_distance(first: QPointF, second: QPointF) -> float:
    """Return Euclidean distance between two scene points."""
    delta = first - second
    return math.hypot(delta.x(), delta.y())


__all__ = [
    "SharedEdgeParticipant",
    "inverse_shared_boundary",
    "shared_boundary_with_points",
    "shared_endpoint_indexes",
    "shared_translation_indexes",
]
