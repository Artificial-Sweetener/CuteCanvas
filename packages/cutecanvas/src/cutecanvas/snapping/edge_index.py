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

"""Bounded spatial lookup for immutable oriented snap edges."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from PySide6.QtCore import QPointF

from .edge_model import OrientedEdge

_MAX_BUCKETS_PER_EDGE = 256


@dataclass(frozen=True, slots=True)
class OrientedEdgeIndex:
    """Index finite edges into scene-space cells for interactive lookup."""

    edges: tuple[OrientedEdge, ...]
    cell_size: float
    buckets: Mapping[tuple[int, int], tuple[int, ...]]
    broad_edges: tuple[int, ...] = ()

    @classmethod
    def build(
        cls,
        edges: tuple[OrientedEdge, ...],
        *,
        scene_units_per_device_pixel: float,
    ) -> OrientedEdgeIndex:
        """Build one bounded index at the active viewport scale."""
        scale = float(scene_units_per_device_pixel)
        if not math.isfinite(scale) or scale <= 0.0:
            raise ValueError("scene units per device pixel must be positive")
        cell_size = max(scale * 32.0, 1e-6)
        mutable: dict[tuple[int, int], list[int]] = defaultdict(list)
        broad: list[int] = []
        for index, edge in enumerate(edges):
            cells = _edge_cells(edge, cell_size)
            if len(cells) > _MAX_BUCKETS_PER_EDGE:
                broad.append(index)
                continue
            for cell in cells:
                mutable[cell].append(index)
        return cls(
            tuple(edges),
            cell_size,
            MappingProxyType(
                {cell: tuple(indexes) for cell, indexes in mutable.items()}
            ),
            tuple(broad),
        )

    def near_point(self, point: QPointF, radius: float) -> tuple[OrientedEdge, ...]:
        """Return deterministically ordered edges near one scene point."""
        distance = max(0.0, float(radius))
        indexes = self._indexes_for_bounds(
            point.x() - distance,
            point.y() - distance,
            point.x() + distance,
            point.y() + distance,
        )
        return tuple(
            self.edges[index]
            for index in indexes
            if self.edges[index].distance_to_point(point) <= distance
        )

    def near_edge(self, edge: OrientedEdge, radius: float) -> tuple[OrientedEdge, ...]:
        """Return candidate edges near the finite bounds of ``edge``."""
        distance = max(0.0, float(radius))
        left = min(edge.start.x(), edge.end.x()) - distance
        right = max(edge.start.x(), edge.end.x()) + distance
        top = min(edge.start.y(), edge.end.y()) - distance
        bottom = max(edge.start.y(), edge.end.y()) + distance
        return tuple(
            self.edges[index]
            for index in self._indexes_for_bounds(left, top, right, bottom)
        )

    def _indexes_for_bounds(
        self,
        left: float,
        top: float,
        right: float,
        bottom: float,
    ) -> tuple[int, ...]:
        """Return unique indexes whose cells intersect finite bounds."""
        minimum_x = math.floor(left / self.cell_size)
        maximum_x = math.floor(right / self.cell_size)
        minimum_y = math.floor(top / self.cell_size)
        maximum_y = math.floor(bottom / self.cell_size)
        indexes = set(self.broad_edges)
        for cell_x in range(minimum_x, maximum_x + 1):
            for cell_y in range(minimum_y, maximum_y + 1):
                indexes.update(self.buckets.get((cell_x, cell_y), ()))
        return tuple(sorted(indexes))


def _edge_cells(edge: OrientedEdge, cell_size: float) -> tuple[tuple[int, int], ...]:
    """Return every cell touched by one edge's conservative bounds."""
    minimum_x = math.floor(min(edge.start.x(), edge.end.x()) / cell_size)
    maximum_x = math.floor(max(edge.start.x(), edge.end.x()) / cell_size)
    minimum_y = math.floor(min(edge.start.y(), edge.end.y()) / cell_size)
    maximum_y = math.floor(max(edge.start.y(), edge.end.y()) / cell_size)
    return tuple(
        (cell_x, cell_y)
        for cell_x in range(minimum_x, maximum_x + 1)
        for cell_y in range(minimum_y, maximum_y + 1)
    )


__all__ = ["OrientedEdgeIndex"]
