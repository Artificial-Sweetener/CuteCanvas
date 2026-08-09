#    QPane - High-performance PySide6 image viewer
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

"""Validate and triangulate finite piecewise layer boundaries."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF

_MIN_VERTICES = 4
_MAX_VERTICES = 128
_GEOMETRY_EPSILON = 1e-10


def finite_boundary(
    points: tuple[QPointF, ...],
    *,
    name: str,
) -> tuple[QPointF, ...]:
    """Detach and validate one bounded polygon boundary."""
    detached = tuple(finite_point(point, name=f"{name} boundary") for point in points)
    if not _MIN_VERTICES <= len(detached) <= _MAX_VERTICES:
        raise ValueError(
            f"piecewise {name} boundary must contain "
            f"{_MIN_VERTICES} to {_MAX_VERTICES} vertices"
        )
    if any(
        detached[index] == detached[(index + 1) % len(detached)]
        for index in range(len(detached))
    ):
        raise ValueError(f"piecewise {name} boundary edges must be nonzero")
    return detached


def validate_simple_boundary(points: tuple[QPointF, ...], *, name: str) -> int:
    """Return winding after rejecting collapsed or intersecting boundaries."""
    area = polygon_area(points)
    if abs(area) <= scaled_epsilon(points):
        raise ValueError(f"piecewise {name} boundary must enclose finite area")
    if any(
        _adjacent_edges_backtrack(
            points[index - 1],
            points[index],
            points[(index + 1) % len(points)],
        )
        for index in range(len(points))
    ):
        raise ValueError(f"piecewise {name} boundary must be simple")
    for first in range(len(points)):
        first_end = (first + 1) % len(points)
        for second in range(first + 1, len(points)):
            second_end = (second + 1) % len(points)
            if len({first, first_end, second, second_end}) < 4:
                continue
            if _segments_intersect(
                points[first],
                points[first_end],
                points[second],
                points[second_end],
            ):
                raise ValueError(f"piecewise {name} boundary must be simple")
    return 1 if area > 0.0 else -1


def triangulate_boundaries(
    source: tuple[QPointF, ...],
    target: tuple[QPointF, ...],
    winding: int,
) -> tuple[tuple[int, int, int], ...]:
    """Ear-clip one shared index topology valid in source and target space."""
    remaining = list(range(len(source)))
    triangles: list[tuple[int, int, int]] = []
    while len(remaining) > 3:
        ear = next(
            (
                position
                for position in range(len(remaining))
                if _is_shared_ear(source, target, remaining, position, winding)
            ),
            None,
        )
        if ear is None:
            raise ValueError("piecewise boundaries do not share a valid triangulation")
        triangles.append(
            (
                remaining[(ear - 1) % len(remaining)],
                remaining[ear],
                remaining[(ear + 1) % len(remaining)],
            )
        )
        del remaining[ear]
    triangles.append((remaining[0], remaining[1], remaining[2]))
    return tuple(triangles)


def triangle_contains(
    triangle: tuple[QPointF, QPointF, QPointF],
    point: QPointF,
) -> bool:
    """Return closed-triangle containment with scale-aware edge tolerance."""
    tolerance = scaled_epsilon((*triangle, point))
    signs = tuple(
        cross(triangle[(index + 1) % 3] - triangle[index], point - triangle[index])
        for index in range(3)
    )
    return min(signs) >= -tolerance or max(signs) <= tolerance


def finite_triangle(
    points: tuple[QPointF, QPointF, QPointF],
    *,
    name: str,
) -> tuple[QPointF, QPointF, QPointF]:
    """Detach and validate exactly three finite points."""
    if len(points) != 3:
        raise ValueError(f"piecewise {name} patch must contain three points")
    detached = tuple(finite_point(point, name=f"{name} patch") for point in points)
    return detached[0], detached[1], detached[2]


def finite_point(point: QPointF, *, name: str) -> QPointF:
    """Detach one finite point or reject it at the geometry boundary."""
    detached = QPointF(point)
    if not math.isfinite(detached.x()) or not math.isfinite(detached.y()):
        raise ValueError(f"{name} point must be finite")
    return detached


def triangle_area(points: tuple[QPointF, QPointF, QPointF]) -> float:
    """Return twice-scaled signed area of one triangle."""
    return cross(points[1] - points[0], points[2] - points[0])


def scaled_epsilon(points: tuple[QPointF, ...]) -> float:
    """Return a squared-coordinate tolerance for finite geometry tests."""
    scale = max(
        *(abs(value) for point in points for value in (point.x(), point.y())),
        1.0,
    )
    return _GEOMETRY_EPSILON * scale * scale


def bounding_rect(points: tuple[QPointF, ...]) -> QRectF:
    """Return finite axis-aligned bounds around detached points."""
    left = min(point.x() for point in points)
    top = min(point.y() for point in points)
    right = max(point.x() for point in points)
    bottom = max(point.y() for point in points)
    return QRectF(left, top, right - left, bottom - top)


def cross(first: QPointF, second: QPointF) -> float:
    """Return the scalar cross product of two planar vectors."""
    return first.x() * second.y() - first.y() * second.x()


def polygon_area(points: tuple[QPointF, ...]) -> float:
    """Return twice-scaled signed area of one ordered polygon."""
    return sum(
        point.x() * points[(index + 1) % len(points)].y()
        - points[(index + 1) % len(points)].x() * point.y()
        for index, point in enumerate(points)
    )


def _is_shared_ear(
    source: tuple[QPointF, ...],
    target: tuple[QPointF, ...],
    remaining: list[int],
    position: int,
    winding: int,
) -> bool:
    """Return whether one index ear is nondegenerate and empty in both spaces."""
    indexes = (
        remaining[(position - 1) % len(remaining)],
        remaining[position],
        remaining[(position + 1) % len(remaining)],
    )
    source_triangle = tuple(source[index] for index in indexes)
    target_triangle = tuple(target[index] for index in indexes)
    if winding * triangle_area(source_triangle) <= scaled_epsilon(
        source_triangle
    ) or winding * triangle_area(target_triangle) <= scaled_epsilon(target_triangle):
        return False
    excluded = set(indexes)
    return not any(
        _triangle_contains_strict(source_triangle, source[index])
        or _triangle_contains_strict(target_triangle, target[index])
        for index in remaining
        if index not in excluded
    )


def _triangle_contains_strict(
    triangle: tuple[QPointF, QPointF, QPointF],
    point: QPointF,
) -> bool:
    """Return whether one point lies strictly inside a triangle."""
    tolerance = scaled_epsilon((*triangle, point))
    signs = tuple(
        cross(triangle[(index + 1) % 3] - triangle[index], point - triangle[index])
        for index in range(3)
    )
    return min(signs) > tolerance or max(signs) < -tolerance


def _adjacent_edges_backtrack(
    previous: QPointF,
    vertex: QPointF,
    following: QPointF,
) -> bool:
    """Reject an adjacent collinear edge that reverses over its predecessor."""
    incoming = vertex - previous
    outgoing = following - vertex
    if abs(cross(incoming, outgoing)) > scaled_epsilon((previous, vertex, following)):
        return False
    return incoming.x() * outgoing.x() + incoming.y() * outgoing.y() < 0.0


def _segments_intersect(
    first_start: QPointF,
    first_end: QPointF,
    second_start: QPointF,
    second_end: QPointF,
) -> bool:
    """Return whether two nonadjacent closed segments intersect."""
    points = (first_start, first_end, second_start, second_end)
    tolerance = scaled_epsilon(points)
    orientations = (
        cross(first_end - first_start, second_start - first_start),
        cross(first_end - first_start, second_end - first_start),
        cross(second_end - second_start, first_start - second_start),
        cross(second_end - second_start, first_end - second_start),
    )
    if orientations[0] * orientations[1] < -(tolerance * tolerance) and orientations[
        2
    ] * orientations[3] < -(tolerance * tolerance):
        return True
    return any(
        abs(orientation) <= tolerance and _point_on_segment(point, start, end)
        for orientation, point, start, end in (
            (orientations[0], second_start, first_start, first_end),
            (orientations[1], second_end, first_start, first_end),
            (orientations[2], first_start, second_start, second_end),
            (orientations[3], first_end, second_start, second_end),
        )
    )


def _point_on_segment(point: QPointF, start: QPointF, end: QPointF) -> bool:
    """Return whether a collinear point lies inside one closed segment bound."""
    scale = max(
        abs(point.x()),
        abs(point.y()),
        abs(start.x()),
        abs(start.y()),
        abs(end.x()),
        abs(end.y()),
        1.0,
    )
    tolerance = _GEOMETRY_EPSILON * scale
    return (
        min(start.x(), end.x()) - tolerance
        <= point.x()
        <= max(start.x(), end.x()) + tolerance
        and min(start.y(), end.y()) - tolerance
        <= point.y()
        <= max(start.y(), end.y()) + tolerance
    )


__all__ = [
    "bounding_rect",
    "cross",
    "finite_boundary",
    "finite_point",
    "finite_triangle",
    "scaled_epsilon",
    "triangle_area",
    "triangle_contains",
    "triangulate_boundaries",
    "validate_simple_boundary",
]
