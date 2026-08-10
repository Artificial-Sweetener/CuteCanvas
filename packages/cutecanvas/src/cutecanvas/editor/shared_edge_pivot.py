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

"""Constrained endpoint pivots for one immutable shared-edge gesture."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QPointF
from qpane.sdk.scene import (
    LayerMapping,
    PiecewiseLayerTransform,
)

from cutecanvas.snapping.edge_model import OrientedEdge

from .shared_edge_collapse import joined_edge_mapping
from .shared_edge_geometry import SharedEdgeSeam
from .shared_edge_participant import (
    SharedEdgeParticipant,
    shared_exterior_neighbor_index,
)

_DIRECTION_TOLERANCE = 1e-4


class SharedEdgeHandle(str, Enum):
    """Identify the independently hit-testable parts of a shared edge."""

    START = "start"
    MIDDLE = "middle"
    END = "end"


@dataclass(frozen=True, slots=True)
class SharedEdgePivot:
    """Constrain one seam endpoint to a common finite participant rail."""

    handle: SharedEdgeHandle
    moving_point: QPointF
    fixed_point: QPointF
    rail_start: QPointF
    rail_end: QPointF
    participants: tuple[SharedEdgeParticipant, ...]
    corner_indexes: tuple[int, ...]

    def __post_init__(self) -> None:
        """Detach mutable point values and reject non-endpoint handles."""
        if self.handle is SharedEdgeHandle.MIDDLE:
            raise ValueError("a shared-edge pivot requires an endpoint handle")
        for name in ("moving_point", "fixed_point", "rail_start", "rail_end"):
            object.__setattr__(self, name, QPointF(getattr(self, name)))

    @property
    def rail_direction(self) -> QPointF:
        """Return the unit direction of the complete common rail."""
        delta = self.rail_end - self.rail_start
        length = math.hypot(delta.x(), delta.y())
        return QPointF(delta.x() / length, delta.y() / length)

    def constrained_point(
        self,
        pointer: QPointF,
        *,
        endpoint_join_span: float,
    ) -> QPointF:
        """Project onto the rail and join either endpoint within snap distance."""
        direction = self.rail_direction
        rail_length = math.hypot(
            self.rail_end.x() - self.rail_start.x(),
            self.rail_end.y() - self.rail_start.y(),
        )
        join_span = min(max(0.0, float(endpoint_join_span)), rail_length * 0.5)
        projection = QPointF.dotProduct(QPointF(pointer) - self.rail_start, direction)
        if projection <= join_span:
            return QPointF(self.rail_start)
        if projection >= rail_length - join_span:
            return QPointF(self.rail_end)
        distance = min(rail_length, max(0.0, projection))
        return self.rail_start + direction * distance

    def mappings_for_point(
        self,
        point: QPointF,
    ) -> tuple[tuple[uuid.UUID, LayerMapping], ...]:
        """Map every bound participant onto one moved common vertex."""
        target_point = QPointF(point)
        mappings: list[tuple[uuid.UUID, LayerMapping]] = []
        for participant, corner_index in zip(
            self.participants,
            self.corner_indexes,
            strict=True,
        ):
            target = list(participant.scene_boundary)
            target[corner_index] = target_point
            mappings.append(
                (
                    participant.layer_id,
                    _mapping_for_target(
                        participant.source_boundary,
                        tuple(target),
                        moved_index=corner_index,
                    ),
                )
            )
        return tuple(mappings)


def _mapping_for_target(
    source: tuple[QPointF, ...],
    target: tuple[QPointF, ...],
    *,
    moved_index: int,
) -> LayerMapping:
    """Return a continuous mapping, including one exact joined target edge."""
    collapsed = joined_edge_mapping(source, target, moved_index=moved_index)
    return PiecewiseLayerTransform(source, target) if collapsed is None else collapsed


def shared_edge_pivots(
    seam: SharedEdgeSeam,
    edges: tuple[OrientedEdge, ...],
    *,
    tolerance: float,
) -> tuple[SharedEdgePivot | None, SharedEdgePivot | None]:
    """Return endpoint pivots only where every participant forms a common rail."""
    distance = max(1e-9, float(tolerance))
    start_source = _pivot_source(seam, SharedEdgeHandle.START, distance)
    end_source = _pivot_source(seam, SharedEdgeHandle.END, distance)
    return (
        (
            None
            if start_source is None
            else _pivot_at(start_source, edges, SharedEdgeHandle.START, distance)
        ),
        (
            None
            if end_source is None
            else _pivot_at(end_source, edges, SharedEdgeHandle.END, distance)
        ),
    )


def _pivot_source(
    seam: SharedEdgeSeam,
    handle: SharedEdgeHandle,
    tolerance: float,
) -> SharedEdgeSeam | None:
    """Return the complete group or unique atomic span owning one endpoint."""
    moving = seam.start if handle is SharedEdgeHandle.START else seam.end
    if all(
        _participant_endpoint_index(participant, seam, handle, tolerance) is not None
        for participant in seam.participants
    ):
        return seam
    candidates = tuple(
        component
        for component in seam.component_seams
        if min(
            _point_distance(component.start, moving),
            _point_distance(component.end, moving),
        )
        <= tolerance
    )
    return candidates[0] if len(candidates) == 1 else None


def _pivot_at(
    seam: SharedEdgeSeam,
    edges: tuple[OrientedEdge, ...],
    handle: SharedEdgeHandle,
    tolerance: float,
) -> SharedEdgePivot | None:
    """Resolve one endpoint's retained exterior edges into a finite rail."""
    moving = seam.start if handle is SharedEdgeHandle.START else seam.end
    fixed = seam.end if handle is SharedEdgeHandle.START else seam.start
    outgoing: list[QPointF] = []
    rail_points: list[QPointF] = []
    corner_indexes: list[int] = []
    has_collapsed_exterior = False
    for participant in seam.participants:
        corner_index = _participant_endpoint_index(
            participant,
            seam,
            handle,
            tolerance,
        )
        fixed_corner_index = _participant_endpoint_index(
            participant,
            seam,
            (
                SharedEdgeHandle.END
                if handle is SharedEdgeHandle.START
                else SharedEdgeHandle.START
            ),
            tolerance,
        )
        if corner_index is None or fixed_corner_index is None:
            return None
        exterior_index = shared_exterior_neighbor_index(
            participant,
            0 if handle is SharedEdgeHandle.START else 1,
            tolerance,
        )
        if (
            exterior_index is None
            or _point_distance(
                participant.source_boundary[corner_index],
                participant.source_boundary[exterior_index],
            )
            <= tolerance
        ):
            return None
        corner_indexes.append(corner_index)
        exterior = participant.scene_boundary[exterior_index]
        if _point_distance(exterior, moving) <= tolerance:
            has_collapsed_exterior = True
            rail_points.append(QPointF(moving))
            continue
        if not any(
            edge.owner_id == str(participant.layer_id)
            and _edge_connects(edge, moving, exterior, tolerance)
            for edge in edges
        ):
            return None
        if _parallel_vector(exterior - moving, seam.edge.tangent):
            return None
        outgoing.append(exterior)
        rail_points.append(exterior)
    if not outgoing:
        return None
    first = outgoing[0] - moving
    if not all(_parallel_vector(first, point - moving) for point in outgoing[1:]):
        return None
    projections = tuple(
        QPointF.dotProduct(first, point - moving) for point in rail_points
    )
    if not has_collapsed_exterior and (
        min(projections) >= 0.0 or max(projections) <= 0.0
    ):
        return None
    if min(projections) == max(projections):
        return None
    rail_start = rail_points[projections.index(min(projections))]
    rail_end = rail_points[projections.index(max(projections))]
    return SharedEdgePivot(
        handle,
        moving,
        fixed,
        rail_start,
        rail_end,
        seam.participants,
        tuple(corner_indexes),
    )


def _participant_endpoint_index(
    participant: SharedEdgeParticipant,
    seam: SharedEdgeSeam,
    handle: SharedEdgeHandle,
    tolerance: float,
) -> int | None:
    """Return the retained topology index for one seam endpoint."""
    position = 0 if handle is SharedEdgeHandle.START else 1
    index = participant.seam_indexes[position]
    expected = seam.start if position == 0 else seam.end
    actual = participant.scene_boundary[index]
    return (
        index
        if math.hypot(actual.x() - expected.x(), actual.y() - expected.y()) <= tolerance
        else None
    )


def _parallel_vector(first: QPointF, second: QPointF) -> bool:
    """Return whether two nonzero vectors lie on the same infinite line."""
    first_length = math.hypot(first.x(), first.y())
    second_length = math.hypot(second.x(), second.y())
    if first_length <= 1e-12 or second_length <= 1e-12:
        return False
    cross = first.x() * second.y() - first.y() * second.x()
    return abs(cross) <= _DIRECTION_TOLERANCE * first_length * second_length


def _edge_connects(
    edge: OrientedEdge,
    first: QPointF,
    second: QPointF,
    tolerance: float,
) -> bool:
    """Return whether one indexed edge connects two retained vertices."""
    return (
        _point_distance(edge.start, first) <= tolerance
        and _point_distance(edge.end, second) <= tolerance
    ) or (
        _point_distance(edge.end, first) <= tolerance
        and _point_distance(edge.start, second) <= tolerance
    )


def _point_distance(first: QPointF, second: QPointF) -> float:
    """Return Euclidean distance between two scene points."""
    delta = first - second
    return math.hypot(delta.x(), delta.y())


__all__ = ["SharedEdgeHandle", "SharedEdgePivot", "shared_edge_pivots"]
