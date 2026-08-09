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

"""Panel-space presentation for unfinished polygon coverage authorship."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF

from .polygon_coverage_hit_testing import PolygonCoverageHitTester
from .polygon_coverage_session import PolygonCoverageSession

_VERTEX_RADIUS = 4.0
_INSERTION_RADIUS = 3.0


@dataclass(frozen=True, slots=True)
class PolygonCoverageOverlayState:
    """Describe detached panel geometry and active authoring affordances."""

    points: tuple[QPointF, ...]
    pointer: QPointF | None = None
    selected_index: int | None = None
    hovered_vertex_index: int | None = None
    hovered_edge_index: int | None = None

    def __post_init__(self) -> None:
        """Detach mutable Qt point values from interaction state."""
        object.__setattr__(
            self, "points", tuple(QPointF(point) for point in self.points)
        )
        object.__setattr__(
            self,
            "pointer",
            None if self.pointer is None else QPointF(self.pointer),
        )


class PolygonCoveragePresentation:
    """Project target vertices and resolve their panel-space affordances."""

    def __init__(
        self,
        target_to_panel: Callable[[QPointF], QPointF | None],
    ) -> None:
        """Capture one target-owned point projection."""
        self._target_to_panel = target_to_panel
        self._hit_testing = PolygonCoverageHitTester()

    def vertices(
        self,
        session: PolygonCoverageSession | None,
    ) -> tuple[tuple[uuid.UUID, QPointF], ...]:
        """Return current stable vertices projected into the panel."""
        if session is None:
            return ()
        projected = []
        for vertex in session.vertices:
            point = self._target_to_panel(vertex.point)
            if point is not None:
                projected.append((vertex.vertex_id, QPointF(point)))
        return tuple(projected)

    def vertex_at(
        self,
        session: PolygonCoverageSession | None,
        point: QPointF,
    ) -> uuid.UUID | None:
        """Return the closest established panel vertex under one point."""
        return self._hit_testing.vertex_at(point, self.vertices(session))

    def edge_at(
        self,
        session: PolygonCoverageSession | None,
        point: QPointF,
    ) -> int | None:
        """Return the closest established open-chain edge under one point."""
        return self._hit_testing.edge_at(point, self.vertices(session))

    def state(
        self,
        session: PolygonCoverageSession | None,
        *,
        pointer: QPointF | None,
        selected_id: uuid.UUID | None,
        hovered_vertex_id: uuid.UUID | None,
        hovered_edge_index: int | None,
    ) -> PolygonCoverageOverlayState | None:
        """Return detached overlay state for current transient identities."""
        vertices = self.vertices(session)
        if not vertices:
            return None
        identities = tuple(vertex_id for vertex_id, _point in vertices)
        return PolygonCoverageOverlayState(
            tuple(point for _vertex_id, point in vertices),
            pointer,
            None if selected_id not in identities else identities.index(selected_id),
            (
                None
                if hovered_vertex_id not in identities
                else identities.index(hovered_vertex_id)
            ),
            hovered_edge_index,
        )


def draw_polygon_coverage_overlay(
    painter: QPainter,
    state: PolygonCoverageOverlayState,
) -> None:
    """Draw the open chain, provisional closure, vertices, and insertion handle."""
    if not state.points:
        return
    painter.save()
    try:
        path = _preview_path(state)
        painter.setPen(_outline_pen())
        painter.setBrush(QColor(255, 255, 255, 28))
        painter.drawPath(path)
        painter.setBrush(QColor(30, 30, 30, 235))
        for index, point in enumerate(state.points):
            painter.setPen(_vertex_pen(index, state))
            painter.drawEllipse(point, _VERTEX_RADIUS, _VERTEX_RADIUS)
        insertion = _insertion_point(state)
        if insertion is not None:
            painter.setPen(QPen(QColor(255, 255, 255), 1.0))
            painter.setBrush(QColor(255, 64, 160))
            painter.drawEllipse(insertion, _INSERTION_RADIUS, _INSERTION_RADIUS)
    finally:
        painter.restore()


def _preview_path(state: PolygonCoverageOverlayState) -> QPainterPath:
    """Return one open chain with a provisional endpoint and closing edge."""
    points = list(state.points)
    if state.pointer is not None and state.selected_index is None:
        points.append(state.pointer)
    path = QPainterPath()
    path.addPolygon(QPolygonF(points))
    if len(points) >= 3:
        path.closeSubpath()
    return path


def _outline_pen() -> QPen:
    """Return the cosmetic marching outline used by unfinished geometry."""
    pen = QPen(Qt.GlobalColor.white, 1.0, Qt.PenStyle.DashLine)
    pen.setCosmetic(True)
    return pen


def _vertex_pen(index: int, state: PolygonCoverageOverlayState) -> QPen:
    """Return semantic vertex feedback for selection, hover, and closure."""
    if index == state.selected_index:
        color = QColor(255, 64, 160)
    elif index == state.hovered_vertex_index:
        color = QColor(255, 196, 64)
    elif index == 0 and len(state.points) >= 3:
        color = QColor(96, 255, 160)
    else:
        color = QColor(255, 255, 255)
    pen = QPen(color, 2.0)
    pen.setCosmetic(True)
    return pen


def _insertion_point(state: PolygonCoverageOverlayState) -> QPointF | None:
    """Return the midpoint affordance for the currently hovered established edge."""
    index = state.hovered_edge_index
    if index is None or not 0 <= index < len(state.points) - 1:
        return None
    return (state.points[index] + state.points[index + 1]) * 0.5


__all__ = [
    "PolygonCoverageOverlayState",
    "PolygonCoveragePresentation",
    "draw_polygon_coverage_overlay",
]
