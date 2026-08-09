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

"""Content-tight polygon boundaries for raster coverage manipulation."""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF

from ..raster.sparse_grid import SparseRasterSnapshot
from .surface import CoverageSnapshot


def coverage_convex_boundary(
    snapshot: CoverageSnapshot,
    *,
    simplification_tolerance: float = 1.25,
) -> tuple[QPointF, ...]:
    """Return a simplified convex boundary around occupied coverage cells."""
    bounds = snapshot.bounds
    pixels = snapshot.pixels
    if bounds is None or pixels.size == 0:
        return ()
    occupied = pixels >= 128
    rows = np.flatnonzero(np.any(occupied, axis=1))
    if rows.size == 0:
        return ()
    extrema: dict[int, tuple[int, int]] = {}
    for row in rows:
        columns = np.flatnonzero(occupied[int(row)])
        extrema[bounds.y + int(row)] = (
            bounds.x + int(columns[0]),
            bounds.x + int(columns[-1]) + 1,
        )
    return _boundary_from_row_extrema(extrema, simplification_tolerance)


def sparse_coverage_convex_boundary(
    snapshot: SparseRasterSnapshot,
    *,
    simplification_tolerance: float = 1.25,
) -> tuple[QPointF, ...]:
    """Return a polygon without materializing transparent sparse gaps."""
    logical = snapshot.bounds
    if logical is None or snapshot.channels != 1:
        return ()
    extrema: dict[int, tuple[int, int]] = {}
    for tile in snapshot.tiles:
        overlap = tile.bounds.intersection(logical)
        if overlap is None:
            continue
        source_x = overlap.x - tile.bounds.x
        source_y = overlap.y - tile.bounds.y
        pixels = tile.pixels[
            source_y : source_y + overlap.height,
            source_x : source_x + overlap.width,
        ]
        occupied = pixels >= 128
        for local_row in np.flatnonzero(np.any(occupied, axis=1)):
            columns = np.flatnonzero(occupied[int(local_row)])
            scene_row = overlap.y + int(local_row)
            left = overlap.x + int(columns[0])
            right = overlap.x + int(columns[-1]) + 1
            current = extrema.get(scene_row)
            extrema[scene_row] = (
                left if current is None else min(left, current[0]),
                right if current is None else max(right, current[1]),
            )
    return _boundary_from_row_extrema(extrema, simplification_tolerance)


def _boundary_from_row_extrema(
    extrema: dict[int, tuple[int, int]],
    simplification_tolerance: float,
) -> tuple[QPointF, ...]:
    """Build one simplified hull from occupied row intervals."""
    points: list[tuple[float, float]] = []
    for row, (left, right) in extrema.items():
        top = float(row)
        bottom = top + 1.0
        points.extend(
            (
                (float(left), top),
                (float(right), top),
                (float(right), bottom),
                (float(left), bottom),
            )
        )
    hull = _convex_hull(points)
    simplified = _simplify_closed(hull, max(0.0, float(simplification_tolerance)))
    return tuple(QPointF(x, y) for x, y in simplified)


def _convex_hull(
    points: list[tuple[float, float]],
) -> tuple[tuple[float, float], ...]:
    """Return the counter-clockwise monotonic-chain hull of finite points."""
    ordered = sorted(set(points))
    if len(ordered) <= 2:
        return tuple(ordered)

    def cross(
        origin: tuple[float, float],
        first: tuple[float, float],
        second: tuple[float, float],
    ) -> float:
        """Return the signed turn from the first ray to the second."""
        return (first[0] - origin[0]) * (second[1] - origin[1]) - (
            first[1] - origin[1]
        ) * (second[0] - origin[0])

    lower: list[tuple[float, float]] = []
    for point in ordered:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0.0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(ordered):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0.0:
            upper.pop()
        upper.append(point)
    return (*lower[:-1], *upper[:-1])


def _simplify_closed(
    points: tuple[tuple[float, float], ...],
    tolerance: float,
) -> tuple[tuple[float, float], ...]:
    """Remove hull vertices lying within tolerance of adjacent edge lines."""
    if len(points) <= 3 or tolerance <= 0.0:
        return points
    retained = list(points)
    changed = True
    while changed and len(retained) > 3:
        changed = False
        for index, point in enumerate(retained):
            previous = retained[index - 1]
            following = retained[(index + 1) % len(retained)]
            if _line_distance(point, previous, following) <= tolerance:
                retained.pop(index)
                changed = True
                break
    return tuple(retained)


def _line_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    """Return perpendicular distance to the infinite line through two points."""
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= 1e-12:
        return math.inf
    return abs(dx * (start[1] - point[1]) - (start[0] - point[0]) * dy) / length


__all__ = ["coverage_convex_boundary", "sparse_coverage_convex_boundary"]
