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

"""Boundary-preserving translation of one finite shared edge."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Protocol

from PySide6.QtCore import QPointF
from qpane.sdk.scene import (
    LayerMapping,
    PiecewiseLayerTransform,
    TriangularLayerMappingPatch,
)

_SEARCH_STEPS = 24
_OFFSET_EPSILON = 1e-9


class _TranslationParticipant(Protocol):
    """Provide immutable participant geometry required by seam translation."""

    layer_id: uuid.UUID
    initial_mapping: LayerMapping
    source_boundary: tuple[QPointF, ...]
    scene_boundary: tuple[QPointF, ...]
    seam_indexes: tuple[int, int]
    translation_indexes: tuple[int, ...]
    interior_side: int


@dataclass(frozen=True, slots=True)
class SharedEdgeTranslation:
    """Return one legal seam displacement and every exact participant mapping."""

    distance: float
    mappings: tuple[tuple[uuid.UUID, LayerMapping], ...]

    def __post_init__(self) -> None:
        """Reject an unusable resolved displacement."""
        if not math.isfinite(self.distance):
            raise ValueError("shared-edge translation distance must be finite")


def resolve_shared_edge_translation(
    *,
    normal: QPointF,
    participants: tuple[_TranslationParticipant, ...],
    distance: float,
    minimum_thickness: float,
) -> SharedEdgeTranslation:
    """Resolve one displacement while preserving straight seam extensions."""
    requested = float(distance)
    thickness = float(minimum_thickness)
    if not math.isfinite(requested):
        raise ValueError("shared-edge translation distance must be finite")
    if not math.isfinite(thickness) or thickness <= 0.0:
        raise ValueError("shared-edge minimum thickness must be positive and finite")
    try:
        mappings = _mappings_for_distance(
            normal,
            participants,
            requested,
            thickness,
        )
    except ValueError:
        resolved, mappings = _nearest_valid_translation(
            normal,
            participants,
            requested,
            thickness,
        )
        return SharedEdgeTranslation(resolved, mappings)
    return SharedEdgeTranslation(requested, mappings)


def _mappings_for_distance(
    normal: QPointF,
    participants: tuple[_TranslationParticipant, ...],
    distance: float,
    minimum_thickness: float,
) -> tuple[tuple[uuid.UUID, LayerMapping], ...]:
    """Map each seam and its straight extensions within frozen boundaries."""
    if abs(distance) <= _OFFSET_EPSILON:
        return tuple(
            (participant.layer_id, participant.initial_mapping)
            for participant in participants
        )
    displacement = normal * distance
    mappings: list[tuple[uuid.UUID, LayerMapping]] = []
    for participant in participants:
        target = tuple(
            (
                point + displacement
                if index in participant.translation_indexes
                else QPointF(point)
            )
            for index, point in enumerate(participant.scene_boundary)
        )
        if (
            _signed_area_twice(participant.scene_boundary) * _signed_area_twice(target)
            <= 0.0
        ):
            raise ValueError("shared-edge translation reverses boundary winding")
        initial_clearance = _boundary_clearance(
            participant.scene_boundary,
            participant.translation_indexes,
        )
        required_clearance = min(minimum_thickness, initial_clearance)
        if (
            _boundary_clearance(target, participant.translation_indexes)
            < required_clearance - _OFFSET_EPSILON
        ):
            raise ValueError("shared-edge translation violates minimum thickness")
        mapping = _mapping_for_boundaries(participant.source_boundary, target)
        mappings.append((participant.layer_id, mapping))
    return tuple(mappings)


def _mapping_for_boundaries(
    source: tuple[QPointF, ...],
    target: tuple[QPointF, ...],
) -> LayerMapping:
    """Prefer one exact affine mapping before constructing finite patches."""
    for index in range(len(source)):
        indexes = (index - 1, index, (index + 1) % len(source))
        try:
            affine = TriangularLayerMappingPatch(
                tuple(source[position] for position in indexes),
                tuple(target[position] for position in indexes),
            ).transform
        except ValueError:
            continue
        if all(
            _points_close(affine.map_point(source_point), target_point)
            for source_point, target_point in zip(source, target, strict=True)
        ):
            return affine
        break
    if len(source) == 3:
        raise ValueError("shared-edge triangle does not define an affine mapping")
    return PiecewiseLayerTransform(source, target)


def _points_close(first: QPointF, second: QPointF) -> bool:
    """Return whether two mapped vertices agree at scene-coordinate precision."""
    scale = max(
        abs(first.x()),
        abs(first.y()),
        abs(second.x()),
        abs(second.y()),
        1.0,
    )
    return math.hypot(first.x() - second.x(), first.y() - second.y()) <= 1e-9 * scale


def _nearest_valid_translation(
    normal: QPointF,
    participants: tuple[_TranslationParticipant, ...],
    requested: float,
    minimum_thickness: float,
) -> tuple[float, tuple[tuple[uuid.UUID, LayerMapping], ...]]:
    """Return the farthest valid mapping on the continuous path from zero."""
    valid_fraction = 0.0
    invalid_fraction = 1.0
    valid_mappings = _mappings_for_distance(
        normal,
        participants,
        0.0,
        minimum_thickness,
    )
    for _step in range(_SEARCH_STEPS):
        fraction = (valid_fraction + invalid_fraction) * 0.5
        candidate = requested * fraction
        try:
            candidate_mappings = _mappings_for_distance(
                normal,
                participants,
                candidate,
                minimum_thickness,
            )
        except ValueError:
            invalid_fraction = fraction
        else:
            valid_fraction = fraction
            valid_mappings = candidate_mappings
    return requested * valid_fraction, valid_mappings


def _boundary_clearance(
    boundary: tuple[QPointF, ...],
    moving_indexes: tuple[int, ...],
) -> float:
    """Return the seam's nearest finite collision within one boundary."""
    moving = set(moving_indexes)
    seam_start, seam_end = max(
        (
            (boundary[first], boundary[second])
            for first in moving_indexes
            for second in moving_indexes
            if first < second
        ),
        key=lambda points: _point_distance(*points),
    )
    clearance = math.inf
    for index, edge_start in enumerate(boundary):
        next_index = (index + 1) % len(boundary)
        edge_end = boundary[next_index]
        edge_indexes = {index, next_index}
        shared_indexes = edge_indexes.intersection(moving)
        if edge_indexes.issubset(moving):
            continue
        if shared_indexes:
            clearance = min(clearance, _point_distance(edge_start, edge_end))
            continue
        clearance = min(
            clearance,
            _segment_distance(seam_start, seam_end, edge_start, edge_end),
        )
    if not math.isfinite(clearance):
        raise ValueError("shared-edge participant has no exterior boundary")
    return clearance


def _segment_distance(
    first_start: QPointF,
    first_end: QPointF,
    second_start: QPointF,
    second_end: QPointF,
) -> float:
    """Return the Euclidean distance between two finite segments."""
    return min(
        _point_segment_distance(first_start, second_start, second_end),
        _point_segment_distance(first_end, second_start, second_end),
        _point_segment_distance(second_start, first_start, first_end),
        _point_segment_distance(second_end, first_start, first_end),
    )


def _point_segment_distance(point: QPointF, start: QPointF, end: QPointF) -> float:
    """Return the Euclidean distance from one point to a finite segment."""
    segment = end - start
    length_squared = QPointF.dotProduct(segment, segment)
    if length_squared <= _OFFSET_EPSILON:
        return _point_distance(point, start)
    fraction = max(
        0.0,
        min(1.0, QPointF.dotProduct(point - start, segment) / length_squared),
    )
    return _point_distance(point, start + segment * fraction)


def _point_distance(first: QPointF, second: QPointF) -> float:
    """Return the Euclidean distance between two points."""
    return math.hypot(first.x() - second.x(), first.y() - second.y())


def _signed_area_twice(boundary: tuple[QPointF, ...]) -> float:
    """Return twice one finite boundary's signed area."""
    return sum(
        point.x() * boundary[(index + 1) % len(boundary)].y()
        - boundary[(index + 1) % len(boundary)].x() * point.y()
        for index, point in enumerate(boundary)
    )


__all__ = ["SharedEdgeTranslation", "resolve_shared_edge_translation"]
