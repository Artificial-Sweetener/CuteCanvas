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
"""Resolve shared-edge handles and their valid endpoint pivots."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF
from qpane.sdk.scene import SceneDescriptor

from .shared_edge_geometry import SharedEdgeSeam
from .shared_edge_index import SharedEdgeDiscoveryIndex
from .shared_edge_pivot import SharedEdgeHandle, SharedEdgePivot


class SharedEdgeHandleResolver:
    """Own device-scale hit priority and endpoint-pivot lookup."""

    def __init__(
        self,
        *,
        active_scene: Callable[[], SceneDescriptor | None],
        discovery: SharedEdgeDiscoveryIndex,
        scale: Callable[[], float],
    ) -> None:
        """Bind current scene, discovery, and device-scale sources."""
        self._active_scene = active_scene
        self._discovery = discovery
        self._scale = scale

    def handle_at(self, seam: SharedEdgeSeam, point: QPointF) -> SharedEdgeHandle:
        """Resolve endpoint handles ahead of the parallel-resize seam body."""
        radius = 8.0 * self._scale()
        distances = (
            (_point_distance(point, seam.start), SharedEdgeHandle.START),
            (_point_distance(point, seam.end), SharedEdgeHandle.END),
        )
        distance, handle = min(distances, key=lambda value: value[0])
        return handle if distance <= radius else SharedEdgeHandle.MIDDLE

    def pivot_for(
        self,
        seam: SharedEdgeSeam | None,
        handle: SharedEdgeHandle | None,
    ) -> SharedEdgePivot | None:
        """Return the frozen endpoint constraint associated with one hover."""
        if seam is None or handle is None or handle is SharedEdgeHandle.MIDDLE:
            return None
        scene = self._active_scene()
        if scene is None:
            return None
        discovery = self._discovery.get(scene)
        if discovery is None:
            return None
        start, end = discovery.pivots(seam)
        return start if handle is SharedEdgeHandle.START else end


def _point_distance(first: QPointF, second: QPointF) -> float:
    """Return Euclidean scene distance between two points."""
    delta = first - second
    return QPointF.dotProduct(delta, delta) ** 0.5


__all__ = ["SharedEdgeHandleResolver"]
