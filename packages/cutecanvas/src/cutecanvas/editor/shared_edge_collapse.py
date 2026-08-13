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

"""Watertight finite-cage mapping for one exactly joined shared edge."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF

from qpane.sdk.scene import (
    BilinearLayerTransform,
    LayerMapping,
    PiecewiseLayerTransform,
)

_COLLINEAR_TOLERANCE = 1e-9


@dataclass(frozen=True, slots=True)
class _BoundaryVertex:
    """Pair one detached boundary point with its original topology index."""

    original_index: int
    point: QPointF


def joined_edge_mapping(
    source: tuple[QPointF, ...],
    target: tuple[QPointF, ...],
    *,
    moved_index: int,
) -> LayerMapping | None:
    """Return a seam-free mapping for one joined edge, or ``None`` otherwise."""
    if len(source) != len(target):
        raise ValueError("joined mapping boundaries must share one topology")
    collapsed_edge = _single_joined_edge(target)
    if collapsed_edge is None:
        return None
    if len(source) == 4 and len(target) == 4:
        source_quad = _rotated_quad(source, collapsed_edge)
        target_quad = _rotated_quad(target, collapsed_edge)
        return BilinearLayerTransform(source_quad, target_quad)
    joined_indexes = {collapsed_edge, (collapsed_edge + 1) % len(target)}
    if moved_index not in joined_indexes:
        raise ValueError("joined mapping must identify the moved endpoint")

    source_vertices = _simplified_vertices(source, minimum=4)
    if len(source_vertices) != 4:
        raise ValueError("joined mapping source must reduce to a quadrilateral")
    target_vertices = _simplified_vertices(
        tuple(point for index, point in enumerate(target) if index != moved_index),
        minimum=3,
        original_indexes=tuple(
            index for index in range(len(target)) if index != moved_index
        ),
    )
    if len(target_vertices) == 3:
        source_quad = _source_quad_from_join(source_vertices, collapsed_edge)
        retained_index = next(index for index in joined_indexes if index != moved_index)
        target_quad = _collapsed_triangle(target_vertices, retained_index)
        return BilinearLayerTransform(
            source_quad,
            target_quad,
        )
    elif len(target_vertices) == 4:
        source_quad = _best_aligned_source_quad(source_vertices, target_vertices)
        target_quad = _points_quad(target_vertices)
    else:
        raise ValueError("joined mapping target must reduce to three or four corners")
    return PiecewiseLayerTransform(source_quad, target_quad)


def _single_joined_edge(boundary: tuple[QPointF, ...]) -> int | None:
    """Return one exact joined edge or reject ambiguous target topology."""
    matches = tuple(
        index
        for index, point in enumerate(boundary)
        if point == boundary[(index + 1) % len(boundary)]
    )
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError("shared-edge pivot may join only one participant edge")
    return matches[0]


def _simplified_vertices(
    boundary: tuple[QPointF, ...],
    *,
    minimum: int,
    original_indexes: tuple[int, ...] | None = None,
) -> tuple[_BoundaryVertex, ...]:
    """Remove collinear boundary vertices down to the required corner count."""
    indexes = original_indexes or tuple(range(len(boundary)))
    vertices = [
        _BoundaryVertex(index, QPointF(point))
        for index, point in zip(indexes, boundary, strict=True)
    ]
    while len(vertices) > minimum:
        removable = next(
            (
                position
                for position in range(len(vertices))
                if _between_neighbors(vertices, position)
            ),
            None,
        )
        if removable is None:
            break
        del vertices[removable]
    return tuple(vertices)


def _between_neighbors(vertices: list[_BoundaryVertex], position: int) -> bool:
    """Return whether one point lies strictly inside its neighboring segment."""
    previous = vertices[position - 1].point
    point = vertices[position].point
    following = vertices[(position + 1) % len(vertices)].point
    edge = following - previous
    relative = point - previous
    length_squared = QPointF.dotProduct(edge, edge)
    if length_squared <= 1e-18:
        return False
    cross = edge.x() * relative.y() - edge.y() * relative.x()
    if abs(cross) > _COLLINEAR_TOLERANCE * max(1.0, length_squared):
        return False
    projection = QPointF.dotProduct(relative, edge) / length_squared
    return 0.0 < projection < 1.0


def _source_quad_from_join(
    source: tuple[_BoundaryVertex, ...],
    collapsed_edge: int,
) -> tuple[QPointF, QPointF, QPointF, QPointF]:
    """Order the source quad from the first vertex of the joined edge."""
    start = next(
        position
        for position, vertex in enumerate(source)
        if vertex.original_index == collapsed_edge
    )
    ordered = tuple(source[(start + offset) % 4].point for offset in range(4))
    return ordered[0], ordered[1], ordered[2], ordered[3]


def _collapsed_triangle(
    target: tuple[_BoundaryVertex, ...],
    joined_index: int,
) -> tuple[QPointF, QPointF, QPointF, QPointF]:
    """Represent one exact joined edge before its remaining triangle edges."""
    joined_position = next(
        position
        for position, vertex in enumerate(target)
        if vertex.original_index == joined_index
    )
    joined = target[joined_position].point
    remaining = tuple(target[(joined_position + offset) % 3].point for offset in (1, 2))
    return joined, joined, remaining[0], remaining[1]


def _best_aligned_source_quad(
    source: tuple[_BoundaryVertex, ...],
    target: tuple[_BoundaryVertex, ...],
) -> tuple[QPointF, QPointF, QPointF, QPointF]:
    """Choose the cyclic source order preserving the most unchanged corners."""
    start = max(
        range(4),
        key=lambda position: sum(
            source[(position + offset) % 4].original_index
            == target[offset].original_index
            for offset in range(4)
        ),
    )
    ordered = tuple(source[(start + offset) % 4].point for offset in range(4))
    return ordered[0], ordered[1], ordered[2], ordered[3]


def _points_quad(
    vertices: tuple[_BoundaryVertex, ...],
) -> tuple[QPointF, QPointF, QPointF, QPointF]:
    """Return four ordered detached points from validated vertices."""
    return (
        vertices[0].point,
        vertices[1].point,
        vertices[2].point,
        vertices[3].point,
    )


def _rotated_quad(
    points: tuple[QPointF, ...],
    start: int,
) -> tuple[QPointF, QPointF, QPointF, QPointF]:
    """Return four cyclic points beginning at ``start``."""
    ordered = tuple(QPointF(points[(start + offset) % 4]) for offset in range(4))
    return ordered[0], ordered[1], ordered[2], ordered[3]


__all__ = ["joined_edge_mapping"]
