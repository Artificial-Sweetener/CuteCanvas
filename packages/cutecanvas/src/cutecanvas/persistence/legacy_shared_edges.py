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

"""Recover unambiguous shared-edge topology omitted by version 14 archives."""

from __future__ import annotations

import math
import uuid
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, replace

from PySide6.QtCore import QPointF
from qpane.sdk.scene import LayerTransform

from ..composition.geometry_policy import LayerGeometryMode, LayerGeometryPolicy
from ..composition.layers import CompositionLayerInstance
from ..coverage import CoverageAssetSnapshot
from ..coverage.boundary import sparse_coverage_convex_boundary
from ..resources import ProjectResourceReference
from .model import CompositionArchiveSnapshot

_ENDPOINT_TOLERANCE = 2.0
_MAXIMUM_ANGLE_SINE = 0.04
_MAXIMUM_DIVERGENCE_RATIO = 0.04
_MINIMUM_EDGE_LENGTH = 32.0
_MAXIMUM_RECOVERY_LAYERS = 64
_MAXIMUM_RECOVERY_EDGES = 512


@dataclass(frozen=True, slots=True)
class _BoundaryEdge:
    """Identify one ordered edge within a legacy raster boundary."""

    layer_index: int
    edge_index: int
    boundary: tuple[QPointF, ...]

    @property
    def start(self) -> QPointF:
        """Return the edge's first ordered endpoint."""
        return self.boundary[self.edge_index]

    @property
    def end(self) -> QPointF:
        """Return the edge's second ordered endpoint."""
        return self.boundary[(self.edge_index + 1) % len(self.boundary)]

    @property
    def length(self) -> float:
        """Return finite edge length."""
        return _distance(self.start, self.end)


@dataclass(frozen=True, slots=True)
class _LegacyPair:
    """Describe one strongly indicated but raster-drifted shared edge."""

    first: _BoundaryEdge
    second: _BoundaryEdge
    first_common: int
    second_common: int


def recover_version_14_shared_edges(
    archive: CompositionArchiveSnapshot,
) -> CompositionArchiveSnapshot:
    """Adopt inferred polygons only for unambiguous version 14 raster pairs."""
    stacks = {
        composition_id: recover_legacy_layer_stack(layers, archive.masks)
        for composition_id, layers in archive.layer_stacks.items()
    }
    if all(stacks[key] == value for key, value in archive.layer_stacks.items()):
        return archive
    return replace(archive, layer_stacks=stacks)


def recover_legacy_layer_stack(
    layers: tuple[CompositionLayerInstance, ...],
    masks: Mapping[uuid.UUID, CoverageAssetSnapshot],
) -> tuple[CompositionLayerInstance, ...]:
    """Return one stack with only uniquely matched legacy pairs repaired."""
    boundaries: dict[int, tuple[QPointF, ...]] = {}
    for index, layer in enumerate(layers):
        source = layer.source
        if (
            layer.geometry.mode is not LayerGeometryMode.CONTENT
            or layer.transform != LayerTransform()
            or not isinstance(source, ProjectResourceReference)
        ):
            continue
        asset = masks.get(source.resource_id)
        if asset is None or asset.retained.items:
            continue
        boundary = sparse_coverage_convex_boundary(asset.raster)
        if 3 <= len(boundary) <= 128:
            boundaries[index] = boundary
    if len(boundaries) > _MAXIMUM_RECOVERY_LAYERS:
        return layers
    if sum(len(boundary) for boundary in boundaries.values()) > _MAXIMUM_RECOVERY_EDGES:
        return layers
    pairs = tuple(
        pair
        for first_index, first_boundary in boundaries.items()
        for second_index, second_boundary in boundaries.items()
        if first_index < second_index
        for pair in _matching_pairs(
            first_index,
            first_boundary,
            second_index,
            second_boundary,
        )
    )
    participation = Counter(
        edge.layer_index for pair in pairs for edge in (pair.first, pair.second)
    )
    repaired = list(layers)
    for pair in pairs:
        if participation[pair.first.layer_index] != 1:
            continue
        if participation[pair.second.layer_index] != 1:
            continue
        first, second = _canonical_boundaries(pair)
        repaired[pair.first.layer_index] = replace(
            repaired[pair.first.layer_index],
            geometry=_boundary_policy(first),
        )
        repaired[pair.second.layer_index] = replace(
            repaired[pair.second.layer_index],
            geometry=_boundary_policy(second),
        )
    return tuple(repaired)


def _matching_pairs(
    first_index: int,
    first_boundary: tuple[QPointF, ...],
    second_index: int,
    second_boundary: tuple[QPointF, ...],
) -> tuple[_LegacyPair, ...]:
    """Return every strongly indicated convergent edge pair."""
    matches: list[_LegacyPair] = []
    for first_edge_index in range(len(first_boundary)):
        first = _BoundaryEdge(first_index, first_edge_index, first_boundary)
        if first.length < _MINIMUM_EDGE_LENGTH:
            continue
        for second_edge_index in range(len(second_boundary)):
            second = _BoundaryEdge(second_index, second_edge_index, second_boundary)
            pair = _matched_pair(first, second)
            if pair is not None:
                matches.append(pair)
    return tuple(matches)


def _matched_pair(first: _BoundaryEdge, second: _BoundaryEdge) -> _LegacyPair | None:
    """Recognize two long edges sharing an endpoint with bounded raster drift."""
    if second.length < _MINIMUM_EDGE_LENGTH:
        return None
    endpoint_pairs = tuple(
        (distance, first_endpoint, second_endpoint)
        for first_endpoint, first_point in enumerate((first.start, first.end))
        for second_endpoint, second_point in enumerate((second.start, second.end))
        if (distance := _distance(first_point, second_point)) <= _ENDPOINT_TOLERANCE
    )
    if not endpoint_pairs:
        return None
    _distance_value, first_common, second_common = min(endpoint_pairs)
    first_vector = _away_vector(first, first_common)
    second_vector = _away_vector(second, second_common)
    cross = abs(_cross(first_vector, second_vector))
    lengths = first.length * second.length
    if QPointF.dotProduct(first_vector, second_vector) <= 0.0:
        return None
    if cross > _MAXIMUM_ANGLE_SINE * lengths:
        return None
    shorter, shorter_common, longer = (
        (first, first_common, second)
        if first.length <= second.length
        else (second, second_common, first)
    )
    shorter_far = shorter.end if shorter_common == 0 else shorter.start
    divergence = _line_distance(shorter_far, longer.start, longer.end)
    if divergence > max(
        _ENDPOINT_TOLERANCE,
        _MAXIMUM_DIVERGENCE_RATIO * shorter.length,
    ):
        return None
    canonical_normal = QPointF(-first_vector.y(), first_vector.x())
    first_side = QPointF.dotProduct(
        canonical_normal, _center(first.boundary) - first.start
    )
    second_side = QPointF.dotProduct(
        canonical_normal,
        _center(second.boundary) - first.start,
    )
    if first_side * second_side >= 0.0:
        return None
    return _LegacyPair(first, second, first_common, second_common)


def _canonical_boundaries(
    pair: _LegacyPair,
) -> tuple[tuple[QPointF, ...], tuple[QPointF, ...]]:
    """Insert the shorter edge into both polygons as one exact shared segment."""
    if pair.first.length <= pair.second.length:
        canonical = pair.first
        canonical_common = pair.first_common
    else:
        canonical = pair.second
        canonical_common = pair.second_common
    common = canonical.start if canonical_common == 0 else canonical.end
    far = canonical.end if canonical_common == 0 else canonical.start
    return (
        _boundary_with_edge(pair.first, pair.first_common, common, far),
        _boundary_with_edge(pair.second, pair.second_common, common, far),
    )


def _boundary_with_edge(
    edge: _BoundaryEdge,
    common_endpoint: int,
    common: QPointF,
    far: QPointF,
) -> tuple[QPointF, ...]:
    """Replace or split one ordered edge so it contains the canonical segment."""
    points = [QPointF(point) for point in edge.boundary]
    start_index = edge.edge_index
    end_index = (start_index + 1) % len(points)
    local_far = edge.end if common_endpoint == 0 else edge.start
    common_index = start_index if common_endpoint == 0 else end_index
    points[common_index] = QPointF(common)
    if _distance(local_far, far) <= _ENDPOINT_TOLERANCE:
        far_index = end_index if common_endpoint == 0 else start_index
        points[far_index] = QPointF(far)
        return tuple(points)
    if common_endpoint == 0:
        points.insert(start_index + 1, QPointF(far))
    elif end_index == 0:
        points.append(QPointF(far))
    else:
        points.insert(end_index, QPointF(far))
    return tuple(points)


def _boundary_policy(boundary: tuple[QPointF, ...]) -> LayerGeometryPolicy:
    """Return one durable exact policy from detached polygon points."""
    return LayerGeometryPolicy(
        LayerGeometryMode.BOUNDARY,
        custom_boundary=tuple((point.x(), point.y()) for point in boundary),
    )


def _away_vector(edge: _BoundaryEdge, common_endpoint: int) -> QPointF:
    """Return the edge vector pointing away from its matched endpoint."""
    return edge.end - edge.start if common_endpoint == 0 else edge.start - edge.end


def _center(boundary: tuple[QPointF, ...]) -> QPointF:
    """Return one stable vertex-average owner center."""
    return sum(boundary, QPointF()) * (1.0 / len(boundary))


def _cross(first: QPointF, second: QPointF) -> float:
    """Return the signed two-dimensional vector cross product."""
    return first.x() * second.y() - first.y() * second.x()


def _line_distance(point: QPointF, start: QPointF, end: QPointF) -> float:
    """Return perpendicular distance from one point to an infinite line."""
    return abs(_cross(end - start, point - start)) / _distance(start, end)


def _distance(first: QPointF, second: QPointF) -> float:
    """Return Euclidean point distance."""
    return math.hypot(first.x() - second.x(), first.y() - second.y())


__all__ = ["recover_legacy_layer_stack", "recover_version_14_shared_edges"]
