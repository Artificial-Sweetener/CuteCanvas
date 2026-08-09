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

"""Panel-space vertex and segment targeting for polygon coverage tools."""

from __future__ import annotations

import math
import uuid

from PySide6.QtCore import QPointF


class PolygonCoverageHitTester:
    """Resolve stable vertices and ordered edges inside fixed panel radii."""

    def __init__(
        self,
        *,
        vertex_radius: float = 7.0,
        edge_radius: float = 6.0,
    ) -> None:
        """Capture positive device-independent hit radii."""
        if vertex_radius <= 0.0 or edge_radius <= 0.0:
            raise ValueError("polygon hit radii must be positive")
        self._vertex_radius = float(vertex_radius)
        self._edge_radius = float(edge_radius)

    def vertex_at(
        self,
        point: QPointF,
        vertices: tuple[tuple[uuid.UUID, QPointF], ...],
    ) -> uuid.UUID | None:
        """Return the closest stable vertex under one panel point."""
        candidates = tuple(
            (distance, vertex_id)
            for vertex_id, vertex in vertices
            if (distance := point_distance(point, vertex)) <= self._vertex_radius
        )
        return None if not candidates else min(candidates, key=lambda item: item[0])[1]

    def edge_at(
        self,
        point: QPointF,
        vertices: tuple[tuple[uuid.UUID, QPointF], ...],
    ) -> int | None:
        """Return the closest established open-chain edge under one panel point."""
        points = tuple(vertex for _vertex_id, vertex in vertices)
        candidates = tuple(
            (segment_distance(point, points[index], points[index + 1]), index)
            for index in range(len(points) - 1)
        )
        eligible = tuple(item for item in candidates if item[0] <= self._edge_radius)
        return None if not eligible else min(eligible)[1]


def point_distance(first: QPointF, second: QPointF) -> float:
    """Return Euclidean panel distance between two points."""
    return math.hypot(first.x() - second.x(), first.y() - second.y())


def segment_distance(point: QPointF, start: QPointF, end: QPointF) -> float:
    """Return Euclidean distance from one point to a finite segment."""
    delta = end - start
    length_squared = QPointF.dotProduct(delta, delta)
    if length_squared <= 1e-12:
        return point_distance(point, start)
    factor = max(
        0.0,
        min(1.0, QPointF.dotProduct(point - start, delta) / length_squared),
    )
    return point_distance(point, start + delta * factor)


__all__ = ["PolygonCoverageHitTester", "point_distance", "segment_distance"]
