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

"""Stable transient topology for unfinished polygon coverage authorship."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, replace

from PySide6.QtCore import QPointF

_MAX_VERTICES = 4096
_AREA_EPSILON = 1e-12


@dataclass(frozen=True, slots=True)
class PolygonCoverageVertex:
    """Identify one editable unfinished-polygon vertex by stable identity."""

    vertex_id: uuid.UUID
    point: QPointF

    def __post_init__(self) -> None:
        """Detach and validate the authored target-coordinate point."""
        point = QPointF(self.point)
        if not math.isfinite(point.x()) or not math.isfinite(point.y()):
            raise ValueError("polygon vertices must be finite")
        object.__setattr__(self, "point", point)


class PolygonCoverageSession:
    """Own revisable vertex topology until one polygon is committed or cancelled."""

    def __init__(self) -> None:
        """Initialize one empty unfinished polygon."""
        self._vertices: list[PolygonCoverageVertex] = []

    @property
    def vertices(self) -> tuple[PolygonCoverageVertex, ...]:
        """Return detached vertices in polygon order."""
        return tuple(
            PolygonCoverageVertex(vertex.vertex_id, vertex.point)
            for vertex in self._vertices
        )

    @property
    def vertex_ids(self) -> tuple[uuid.UUID, ...]:
        """Return stable vertex identities in polygon order."""
        return tuple(vertex.vertex_id for vertex in self._vertices)

    @property
    def points(self) -> tuple[QPointF, ...]:
        """Return detached target-coordinate points in polygon order."""
        return tuple(QPointF(vertex.point) for vertex in self._vertices)

    @property
    def open_endpoint_id(self) -> uuid.UUID | None:
        """Return the vertex from which continued authoring extends."""
        return None if not self._vertices else self._vertices[-1].vertex_id

    @property
    def can_finish(self) -> bool:
        """Return whether the current vertices enclose nondegenerate coverage."""
        return (
            len(self._vertices) >= 3 and abs(_signed_area(self.points)) > _AREA_EPSILON
        )

    def append(self, point: QPointF) -> uuid.UUID:
        """Append one distinct vertex and return its stable identity."""
        self._require_capacity()
        vertex = PolygonCoverageVertex(uuid.uuid4(), point)
        self._require_distinct(vertex.point)
        self._vertices.append(vertex)
        return vertex.vertex_id

    def insert_after(self, vertex_id: uuid.UUID, point: QPointF) -> uuid.UUID:
        """Insert one distinct vertex after an established neighbor."""
        self._require_capacity()
        index = self._index(vertex_id)
        vertex = PolygonCoverageVertex(uuid.uuid4(), point)
        self._require_distinct(vertex.point)
        self._vertices.insert(index + 1, vertex)
        return vertex.vertex_id

    def move(self, vertex_id: uuid.UUID, point: QPointF) -> bool:
        """Move one established vertex without changing order or identity."""
        index = self._index(vertex_id)
        replacement = PolygonCoverageVertex(vertex_id, point)
        current = self._vertices[index]
        if replacement.point == current.point:
            return False
        self._require_distinct(replacement.point, excluding=vertex_id)
        self._vertices[index] = replace(current, point=replacement.point)
        return True

    def remove(self, vertex_id: uuid.UUID) -> bool:
        """Remove one established vertex while leaving the session open."""
        index = self._index_or_none(vertex_id)
        if index is None:
            return False
        del self._vertices[index]
        return True

    def clear(self) -> bool:
        """Discard every unfinished vertex."""
        if not self._vertices:
            return False
        self._vertices.clear()
        return True

    def _require_capacity(self) -> None:
        """Reject topology that exceeds the bounded interactive contract."""
        if len(self._vertices) >= _MAX_VERTICES:
            raise ValueError("polygon vertex limit exceeded")

    def _require_distinct(
        self,
        point: QPointF,
        *,
        excluding: uuid.UUID | None = None,
    ) -> None:
        """Reject exact duplicate vertices that create zero-length edges."""
        if any(
            vertex.vertex_id != excluding and vertex.point == point
            for vertex in self._vertices
        ):
            raise ValueError("polygon vertices must be distinct")

    def _index(self, vertex_id: uuid.UUID) -> int:
        """Return one vertex index or reject a stale identity."""
        index = self._index_or_none(vertex_id)
        if index is None:
            raise KeyError(vertex_id)
        return index

    def _index_or_none(self, vertex_id: uuid.UUID) -> int | None:
        """Return one vertex index when its stable identity remains current."""
        return next(
            (
                index
                for index, vertex in enumerate(self._vertices)
                if vertex.vertex_id == vertex_id
            ),
            None,
        )


def _signed_area(points: tuple[QPointF, ...]) -> float:
    """Return twice-scaled signed polygon area with deterministic ordering."""
    return 0.5 * sum(
        point.x() * points[(index + 1) % len(points)].y()
        - points[(index + 1) % len(points)].x() * point.y()
        for index, point in enumerate(points)
    )


__all__ = ["PolygonCoverageSession", "PolygonCoverageVertex"]
