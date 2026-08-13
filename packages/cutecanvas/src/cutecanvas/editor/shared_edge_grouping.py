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

"""Assemble pairwise overlap evidence into continuous shared-edge groups."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QPointF

from cutecanvas.snapping.edge_model import OrientedEdge

from .shared_edge_geometry import SharedEdgeSeam
from .shared_edge_participant import (
    SharedEdgeParticipant,
    inverse_shared_boundary,
    shared_boundary_with_points,
    shared_endpoint_indexes,
    shared_translation_indexes,
)


def grouped_shared_edges(
    pair_seams: tuple[SharedEdgeSeam, ...],
    *,
    tolerance: float,
) -> tuple[SharedEdgeSeam, ...]:
    """Return maximal connected groups from atomic opposite-side overlaps."""
    remaining = list(pair_seams)
    groups: list[SharedEdgeSeam] = []
    while remaining:
        component = [remaining.pop(0)]
        changed = True
        while changed:
            changed = False
            for candidate in tuple(remaining):
                if any(
                    _connected(existing, candidate, tolerance) for existing in component
                ):
                    component.append(candidate)
                    remaining.remove(candidate)
                    changed = True
        groups.append(_merge_component(tuple(component), tolerance))
    return tuple(
        sorted(
            groups,
            key=lambda seam: (
                seam.start.x(),
                seam.start.y(),
                seam.end.x(),
                seam.end.y(),
                tuple(str(item.layer_id) for item in seam.participants),
            ),
        )
    )


def _connected(
    first: SharedEdgeSeam,
    second: SharedEdgeSeam,
    tolerance: float,
) -> bool:
    """Return whether two overlap spans share one touching carrier interval."""
    tangent = first.edge.tangent
    other_tangent = second.edge.tangent
    cross = tangent.x() * other_tangent.y() - tangent.y() * other_tangent.x()
    if abs(cross) > 1e-4:
        return False
    normal = first.edge.normal
    if (
        abs(QPointF.dotProduct(normal, second.start) - first.edge.line_offset)
        > tolerance
    ):
        return False
    first_start, first_end = _interval(first, tangent)
    second_start, second_end = _interval(second, tangent)
    return (
        first_end + tolerance >= second_start and second_end + tolerance >= first_start
    )


def _merge_component(
    component: tuple[SharedEdgeSeam, ...],
    tolerance: float,
) -> SharedEdgeSeam:
    """Build one canonical participant snapshot for a connected carrier."""
    reference = component[0]
    tangent = reference.edge.tangent
    normal = reference.edge.normal
    intervals = tuple(_interval(seam, tangent) for seam in component)
    overlap_start = min(interval[0] for interval in intervals)
    overlap_end = max(interval[1] for interval in intervals)
    start = tangent * overlap_start + normal * reference.edge.line_offset
    end = tangent * overlap_end + normal * reference.edge.line_offset
    edge = OrientedEdge(
        reference.edge.owner_id,
        start,
        end,
        reference.edge.owner_center,
        reference.edge.kind,
        max(seam.edge.priority for seam in component),
    )
    layer_ids = sorted(
        {
            participant.layer_id
            for seam in component
            for participant in seam.participants
        },
        key=str,
    )
    participants = tuple(
        _merged_participant(
            layer_id,
            component,
            edge,
            tolerance,
        )
        for layer_id in layer_ids
    )
    return SharedEdgeSeam(
        reference.scene_id,
        edge,
        overlap_start,
        overlap_end,
        participants,
        component,
    )


def _merged_participant(
    layer_id: uuid.UUID,
    component: tuple[SharedEdgeSeam, ...],
    edge: OrientedEdge,
    tolerance: float,
) -> SharedEdgeParticipant:
    """Return one layer boundary split at every relevant group junction."""
    evidence = tuple(
        participant
        for seam in component
        for participant in seam.participants
        if participant.layer_id == layer_id
    )
    base = max(evidence, key=lambda participant: len(participant.scene_boundary))
    additions = tuple(
        point
        for seam in component
        if any(participant.layer_id == layer_id for participant in seam.participants)
        for point in (seam.start, seam.end)
    )
    scene_boundary = shared_boundary_with_points(
        base.scene_boundary,
        additions,
        tolerance,
    )
    source_boundary = inverse_shared_boundary(base.initial_mapping, scene_boundary)
    if source_boundary is None:
        raise ValueError("shared-edge group boundary must remain invertible")
    tangent = edge.tangent
    endpoints = sorted(
        additions,
        key=lambda point: QPointF.dotProduct(tangent, point),
    )
    seam_indexes = shared_endpoint_indexes(
        scene_boundary,
        endpoints[0],
        endpoints[-1],
        tolerance,
    )
    translation_indexes = shared_translation_indexes(
        scene_boundary,
        seam_indexes,
        tolerance,
    )
    center = sum(scene_boundary, QPointF()) * (1.0 / len(scene_boundary))
    side = QPointF.dotProduct(edge.normal, center) - edge.line_offset
    if abs(side) <= tolerance:
        raise ValueError("shared-edge participant must occupy one carrier side")
    return SharedEdgeParticipant(
        layer_id,
        base.initial_mapping,
        source_boundary,
        scene_boundary,
        seam_indexes,
        translation_indexes,
        -1 if side < 0.0 else 1,
    )


def _interval(seam: SharedEdgeSeam, tangent: QPointF) -> tuple[float, float]:
    """Project one seam onto a canonical unit tangent."""
    values = (
        QPointF.dotProduct(tangent, seam.start),
        QPointF.dotProduct(tangent, seam.end),
    )
    return min(values), max(values)


__all__ = ["grouped_shared_edges"]
