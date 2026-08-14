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

"""Eligibility and coupled affine geometry for shared layer edges."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from PySide6.QtCore import QPointF

from cutecanvas.snapping.edge_model import OrientedEdge
from qpane.sdk.scene import LayerMapping

from .shared_edge_participant import (
    SharedEdgeParticipant,
    inverse_shared_boundary,
    shared_boundary_with_points,
    shared_endpoint_indexes,
    shared_translation_indexes,
)
from .shared_edge_translation import (
    SharedEdgeTranslation,
    resolve_shared_edge_translation,
)

_PARALLEL_SINE_TOLERANCE = 1e-4
_AXIS_SINE_TOLERANCE = 1e-6


@dataclass(frozen=True, slots=True)
class SharedEdgeSeam:
    """Describe one continuous coincident seam and all layer participants."""

    scene_id: uuid.UUID
    edge: OrientedEdge
    overlap_start: float
    overlap_end: float
    participants: tuple[SharedEdgeParticipant, ...]
    component_seams: tuple[SharedEdgeSeam, ...] = ()

    def __post_init__(self) -> None:
        """Require at least two uniquely identified seam participants."""
        identities = tuple(item.layer_id for item in self.participants)
        if len(identities) < 2 or len(set(identities)) != len(identities):
            raise ValueError("shared edges require at least two unique participants")

    @property
    def start(self) -> QPointF:
        """Return the shared finite segment start in scene coordinates."""
        return (
            self.edge.tangent * self.overlap_start
            + self.edge.normal * self.edge.line_offset
        )

    @property
    def end(self) -> QPointF:
        """Return the shared finite segment end in scene coordinates."""
        return (
            self.edge.tangent * self.overlap_end
            + self.edge.normal * self.edge.line_offset
        )

    @property
    def parallel_translation_enabled(self) -> bool:
        """Return whether whole-edge translation is exposed for this axis."""
        tangent = self.edge.tangent
        return (
            abs(tangent.x()) <= _AXIS_SINE_TOLERANCE
            or abs(tangent.y()) <= _AXIS_SINE_TOLERANCE
        )

    def translation_for_distance(
        self,
        distance: float,
        *,
        minimum_thickness: float,
    ) -> SharedEdgeTranslation:
        """Return one legal boundary-preserving midpoint translation."""
        return resolve_shared_edge_translation(
            normal=self.edge.normal,
            participants=self.participants,
            distance=distance,
            minimum_thickness=minimum_thickness,
        )


def shared_edge_seam(
    *,
    scene_id: uuid.UUID,
    first: OrientedEdge,
    second: OrientedEdge,
    first_mapping: LayerMapping,
    second_mapping: LayerMapping,
    first_boundary: tuple[QPointF, ...],
    second_boundary: tuple[QPointF, ...],
    coincidence_tolerance: float,
    minimum_overlap: float,
) -> SharedEdgeSeam | None:
    """Return a valid two-layer seam or ``None`` for unrelated edges."""
    if first.owner_id == second.owner_id or not _parallel(first, second):
        return None
    normal = first.normal
    second_offset = QPointF.dotProduct(normal, second.start)
    if abs(first.line_offset - second_offset) > coincidence_tolerance:
        return None
    second_projection = tuple(
        QPointF.dotProduct(first.tangent, point) for point in (second.start, second.end)
    )
    first_interval = first.projection_interval
    overlap_start = max(first_interval[0], min(second_projection))
    overlap_end = min(first_interval[1], max(second_projection))
    if overlap_end - overlap_start < minimum_overlap:
        return None
    first_side = QPointF.dotProduct(normal, first.owner_center) - first.line_offset
    second_side = QPointF.dotProduct(normal, second.owner_center) - first.line_offset
    if first_side * second_side >= 0.0:
        return None
    try:
        first_id = uuid.UUID(first.owner_id)
        second_id = uuid.UUID(second.owner_id)
    except ValueError:
        return None
    canonical = OrientedEdge(
        first.owner_id,
        first.start,
        first.end,
        first.owner_center,
        first.kind,
        max(first.priority, second.priority),
    )
    seam_start = (
        canonical.tangent * overlap_start + canonical.normal * canonical.line_offset
    )
    seam_end = (
        canonical.tangent * overlap_end + canonical.normal * canonical.line_offset
    )
    first_scene_boundary = shared_boundary_with_points(
        first_boundary,
        (seam_start, seam_end),
        coincidence_tolerance,
    )
    second_scene_boundary = shared_boundary_with_points(
        second_boundary,
        (seam_start, seam_end),
        coincidence_tolerance,
    )
    first_source_boundary = inverse_shared_boundary(first_mapping, first_scene_boundary)
    second_source_boundary = inverse_shared_boundary(
        second_mapping, second_scene_boundary
    )
    if first_source_boundary is None or second_source_boundary is None:
        return None
    try:
        first_seam_indexes = shared_endpoint_indexes(
            first_scene_boundary,
            seam_start,
            seam_end,
            coincidence_tolerance,
        )
        second_seam_indexes = shared_endpoint_indexes(
            second_scene_boundary,
            seam_start,
            seam_end,
            coincidence_tolerance,
        )
    except ValueError:
        return None
    participants = tuple(
        sorted(
            (
                SharedEdgeParticipant(
                    first_id,
                    first_mapping,
                    first_source_boundary,
                    first_scene_boundary,
                    first_seam_indexes,
                    shared_translation_indexes(
                        first_scene_boundary,
                        first_seam_indexes,
                        coincidence_tolerance,
                    ),
                    -1 if first_side < 0.0 else 1,
                ),
                SharedEdgeParticipant(
                    second_id,
                    second_mapping,
                    second_source_boundary,
                    second_scene_boundary,
                    second_seam_indexes,
                    shared_translation_indexes(
                        second_scene_boundary,
                        second_seam_indexes,
                        coincidence_tolerance,
                    ),
                    -1 if second_side < 0.0 else 1,
                ),
            ),
            key=lambda participant: str(participant.layer_id),
        )
    )
    return SharedEdgeSeam(
        scene_id,
        canonical,
        overlap_start,
        overlap_end,
        (participants[0], participants[1]),
    )


def _parallel(first: OrientedEdge, second: OrientedEdge) -> bool:
    """Return whether two canonical tangents share one orientation."""
    return (
        abs(
            first.tangent.x() * second.tangent.y()
            - first.tangent.y() * second.tangent.x()
        )
        <= _PARALLEL_SINE_TOLERANCE
    )


__all__ = [
    "SharedEdgeSeam",
    "shared_edge_seam",
]
