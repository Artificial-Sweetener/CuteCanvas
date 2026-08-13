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

"""Exact stationary finite-edge capture for oriented snapping gestures."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF

from cutecanvas.scene.layer_geometry import LayerGeometryResolver
from qpane.sdk.scene import LayerDescriptor, SceneDescriptor

from .configuration import SnapConfiguration
from .edge_model import (
    OrientedEdge,
    OrientedEdgeKind,
    polygon_edges,
    quadrilateral_edges,
)
from .model import SnapGrid


@dataclass(frozen=True, slots=True)
class OrientedTargetSnapshot:
    """Freeze one scene's configured finite-edge targets for a gesture."""

    scene_id: uuid.UUID
    edges: tuple[OrientedEdge, ...]
    grid: SnapGrid | None


class OrientedEdgeCandidateProvider:
    """Capture exact scene edges without editor gesture or ranking policy."""

    def __init__(
        self,
        *,
        active_scene: Callable[[], SceneDescriptor | None],
        geometry: LayerGeometryResolver,
        configuration: SnapConfiguration,
    ) -> None:
        """Bind authoritative scene geometry and shared snap configuration."""
        self._active_scene = active_scene
        self._geometry = geometry
        self._configuration = configuration

    def capture(
        self,
        *,
        excluded_layer_ids: tuple[uuid.UUID, ...] = (),
        layers_only: bool = False,
    ) -> OrientedTargetSnapshot | None:
        """Return one immutable exact-edge target snapshot."""
        scene = self._active_scene()
        return (
            None
            if scene is None
            else self.capture_scene(
                scene,
                excluded_layer_ids=excluded_layer_ids,
                layers_only=layers_only,
            )
        )

    def capture_scene(
        self,
        scene: SceneDescriptor,
        *,
        excluded_layer_ids: tuple[uuid.UUID, ...] = (),
        layers_only: bool = False,
    ) -> OrientedTargetSnapshot | None:
        """Return exact edge targets from one explicit scene revision."""
        policy = self._configuration.policy
        if not policy.enabled:
            return None
        excluded = frozenset(excluded_layer_ids)
        edges: list[OrientedEdge] = []
        if policy.layers:
            edges.extend(self.layer_edges(scene, excluded_layer_ids=excluded))
        bounds = QRectF(
            scene.bounds.x,
            scene.bounds.y,
            scene.bounds.width,
            scene.bounds.height,
        )
        if not layers_only and policy.canvas:
            edges.extend(_rectangle_edges("composition", bounds, priority=20))
        if not layers_only and policy.guides:
            edges.extend(self._guide_edges(bounds))
        grid = (
            None
            if layers_only or not policy.grid
            else self._configuration.grid_model(bounds)
        )
        return OrientedTargetSnapshot(scene.scene_id, tuple(edges), grid)

    def layer_edges(
        self,
        scene: SceneDescriptor,
        *,
        excluded_layer_ids: frozenset[uuid.UUID] = frozenset(),
    ) -> tuple[OrientedEdge, ...]:
        """Return exact manipulation edges for visible scene layers."""
        edges: list[OrientedEdge] = []
        for layer in scene.layers:
            if not layer.visible or layer.layer_id in excluded_layer_ids:
                continue
            boundary = self._geometry.resolved_scene_boundary(layer)
            if not boundary:
                continue
            edges.extend(
                polygon_edges(
                    str(layer.layer_id),
                    boundary,
                    priority=10,
                )
            )
        return tuple(edges)

    def layer_corners(
        self,
        layer: LayerDescriptor,
    ) -> tuple[QPointF, QPointF, QPointF, QPointF] | tuple[()]:
        """Return exact manipulation corners through the shared geometry owner."""
        return self._geometry.resolved_scene_corners(layer)

    def layer_boundary(self, layer: LayerDescriptor) -> tuple[QPointF, ...]:
        """Return the retained ordered boundary through the geometry owner."""
        return self._geometry.resolved_scene_boundary(layer)

    def _guide_edges(self, bounds: QRectF) -> tuple[OrientedEdge, ...]:
        """Return authored axis guides as finite oriented scene edges."""
        vertical, horizontal = self._configuration.guides
        center = bounds.center()
        return (
            *(
                OrientedEdge(
                    f"guide:x:{index}",
                    QPointF(position, bounds.top()),
                    QPointF(position, bounds.bottom()),
                    center,
                    OrientedEdgeKind.GUIDE,
                    30,
                )
                for index, position in enumerate(vertical)
            ),
            *(
                OrientedEdge(
                    f"guide:y:{index}",
                    QPointF(bounds.left(), position),
                    QPointF(bounds.right(), position),
                    center,
                    OrientedEdgeKind.GUIDE,
                    30,
                )
                for index, position in enumerate(horizontal)
            ),
        )


def _rectangle_edges(
    owner_id: str,
    bounds: QRectF,
    *,
    priority: int,
) -> tuple[OrientedEdge, ...]:
    """Return exact finite edges around one scene rectangle."""
    rectangle = QRectF(bounds).normalized()
    corners = (
        rectangle.topLeft(),
        rectangle.topRight(),
        rectangle.bottomRight(),
        rectangle.bottomLeft(),
    )
    return quadrilateral_edges(
        owner_id,
        corners,
        kind=OrientedEdgeKind.CANVAS,
        priority=priority,
    )


__all__ = ["OrientedEdgeCandidateProvider", "OrientedTargetSnapshot"]
