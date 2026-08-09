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

"""Deterministic hover discovery for inferred shared-edge groups."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeGuard

from PySide6.QtCore import QPointF
from qpane.sdk.scene import (
    BilinearLayerTransform,
    LayerDescriptor,
    PiecewiseLayerTransform,
    SceneDescriptor,
)

from cutecanvas.snapping.edge_index import OrientedEdgeIndex
from cutecanvas.snapping.edge_model import OrientedEdge

from .shared_edge_geometry import SharedEdgeSeam, shared_edge_seam
from .shared_edge_grouping import grouped_shared_edges
from .shared_edge_pivot import SharedEdgePivot, shared_edge_pivots


class SharedEdgeDiscovery:
    """Discover eligible seams from one immutable scene-edge index."""

    def __init__(
        self,
        scene: SceneDescriptor,
        index: OrientedEdgeIndex,
        *,
        scene_units_per_device_pixel: float,
        boundary_for: Callable[[LayerDescriptor], tuple[QPointF, ...]] | None = None,
    ) -> None:
        """Capture layer descriptors, index, and device-scale tolerances."""
        self._scene = scene
        self._index = index
        self._scale = max(1e-9, float(scene_units_per_device_pixel))
        self._layers = {str(layer.layer_id): layer for layer in scene.layers}
        self._boundary_for = boundary_for or _descriptor_boundary
        self._seams: tuple[SharedEdgeSeam, ...] | None = None

    def seams(self) -> tuple[SharedEdgeSeam, ...]:
        """Return every shared-edge group in deterministic order."""
        return self._candidate_seams()

    def seam_at(self, point: QPointF) -> SharedEdgeSeam | None:
        """Return the deterministically best eligible seam under ``point``."""
        hover_radius = 6.0 * self._scale
        seams: dict[tuple[object, ...], SharedEdgeSeam] = {}
        endpoint_seams: dict[tuple[object, ...], SharedEdgeSeam] = {}
        for seam in self._candidate_seams():
            if _distance_to_segment(point, seam.start, seam.end) > hover_radius:
                continue
            identity = _seam_identity(seam)
            seams[identity] = seam
            if (
                min(
                    _point_distance(point, seam.start),
                    _point_distance(point, seam.end),
                )
                <= hover_radius
            ):
                endpoint_seams[identity] = seam
        if len(endpoint_seams) == 1:
            return next(iter(endpoint_seams.values()))
        if len(seams) != 1:
            return None
        return next(iter(seams.values()))

    def pivots(
        self,
        seam: SharedEdgeSeam,
    ) -> tuple[SharedEdgePivot | None, SharedEdgePivot | None]:
        """Return endpoint constraints from the same frozen geometry snapshot."""
        return shared_edge_pivots(
            seam,
            self._index.edges,
            tolerance=max(1e-7, 0.25 * self._scale),
        )

    def _candidate_seams(self) -> tuple[SharedEdgeSeam, ...]:
        """Build and group coincident pair evidence once per frozen index."""
        if self._seams is not None:
            return self._seams
        coincidence = max(1e-7, 0.25 * self._scale)
        minimum_overlap = 8.0 * self._scale
        pair_seams: dict[tuple[object, ...], SharedEdgeSeam] = {}
        for edge in self._index.edges:
            first = self._layers.get(edge.owner_id)
            if not _eligible(first):
                continue
            assert first.transform is not None
            for candidate in self._index.near_edge(edge, coincidence):
                second = self._layers.get(candidate.owner_id)
                if not _eligible(second):
                    continue
                assert second.transform is not None
                first_boundary = self._boundary_for(first)
                second_boundary = self._boundary_for(second)
                if len(first_boundary) < 3 or len(second_boundary) < 3:
                    continue
                seam = shared_edge_seam(
                    scene_id=self._scene.scene_id,
                    first=edge,
                    second=candidate,
                    first_mapping=first.transform,
                    second_mapping=second.transform,
                    first_boundary=first_boundary,
                    second_boundary=second_boundary,
                    coincidence_tolerance=coincidence,
                    minimum_overlap=minimum_overlap,
                )
                if seam is not None:
                    pair_seams.setdefault(_seam_identity(seam), seam)
        grouped = grouped_shared_edges(
            tuple(pair_seams.values()),
            tolerance=coincidence,
        )
        self._seams = tuple(
            seam
            for seam in grouped
            if not any(
                not _eligible(self._layers.get(edge.owner_id))
                and _edge_touches_seam(edge, seam, coincidence)
                for edge in self._index.edges
            )
        )
        return self._seams


def _eligible(layer: LayerDescriptor | None) -> TypeGuard[LayerDescriptor]:
    """Return whether one descriptor supports a nondestructive affine edit."""
    if layer is None:
        return False
    interaction = layer.interaction
    return bool(
        layer.visible
        and layer.transform is not None
        and interaction.selectable
        and interaction.movable
    )


def _descriptor_boundary(
    layer: LayerDescriptor,
) -> tuple[QPointF, ...]:
    """Return retained or storage-bound geometry without an editor resolver."""
    bounds = layer.raster_bounds
    mapping = layer.transform
    if mapping is None:
        return ()
    if isinstance(mapping, (PiecewiseLayerTransform, BilinearLayerTransform)):
        return tuple(QPointF(point) for point in mapping.target_boundary)
    if bounds is None:
        placement = layer.placement
        return (
            QPointF(placement.x, placement.y),
            QPointF(placement.x + placement.width, placement.y),
            QPointF(
                placement.x + placement.width,
                placement.y + placement.height,
            ),
            QPointF(placement.x, placement.y + placement.height),
        )
    return (
        mapping.map_point(QPointF(bounds.x, bounds.y)),
        mapping.map_point(QPointF(bounds.right, bounds.y)),
        mapping.map_point(QPointF(bounds.right, bounds.bottom)),
        mapping.map_point(QPointF(bounds.x, bounds.bottom)),
    )


def _distance_to_segment(point: QPointF, start: QPointF, end: QPointF) -> float:
    """Return Euclidean distance from a point to a finite segment."""
    segment = end - start
    length_squared = QPointF.dotProduct(segment, segment)
    projection = max(
        0.0,
        min(
            1.0,
            QPointF.dotProduct(point - start, segment) / length_squared,
        ),
    )
    closest = start + segment * projection
    delta = point - closest
    return (QPointF.dotProduct(delta, delta)) ** 0.5


def _seam_identity(seam: SharedEdgeSeam) -> tuple[object, ...]:
    """Return one endpoint-order-independent group identity."""
    endpoints = sorted(
        (
            (round(seam.start.x(), 9), round(seam.start.y(), 9)),
            (round(seam.end.x(), 9), round(seam.end.y(), 9)),
        )
    )
    return (
        tuple(sorted(str(item.layer_id) for item in seam.participants)),
        endpoints[0],
        endpoints[1],
    )


def _point_distance(first: QPointF, second: QPointF) -> float:
    """Return Euclidean distance between two points."""
    delta = first - second
    return QPointF.dotProduct(delta, delta) ** 0.5


def _edge_touches_seam(
    edge: OrientedEdge,
    seam: SharedEdgeSeam,
    tolerance: float,
) -> bool:
    """Return whether an indexed edge would extend or overlap one group."""
    tangent = edge.tangent
    seam_tangent = seam.edge.tangent
    cross = tangent.x() * seam_tangent.y() - tangent.y() * seam_tangent.x()
    if abs(cross) > 1e-4:
        return False
    if (
        abs(QPointF.dotProduct(seam.edge.normal, edge.start) - seam.edge.line_offset)
        > tolerance
    ):
        return False
    edge_values = sorted(
        QPointF.dotProduct(seam_tangent, point) for point in (edge.start, edge.end)
    )
    seam_values = sorted(
        QPointF.dotProduct(seam_tangent, point) for point in (seam.start, seam.end)
    )
    return (
        edge_values[1] + tolerance >= seam_values[0]
        and seam_values[1] + tolerance >= edge_values[0]
    )


__all__ = ["SharedEdgeDiscovery"]
