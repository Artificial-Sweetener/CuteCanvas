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

"""Exact rectangle-union coverage for sampled presentation products."""

from __future__ import annotations

from itertools import pairwise

from PySide6.QtCore import QRectF


def rectangles_cover(required: QRectF, candidates: tuple[QRectF, ...]) -> bool:
    """Return whether a rectangle union completely covers ``required``."""
    tolerance = 1e-9
    clipped = tuple(
        candidate.intersected(required)
        for candidate in candidates
        if candidate.intersects(required)
    )
    if not clipped:
        return False
    left = required.x()
    right = left + required.width()
    top = required.y()
    bottom = top + required.height()
    x_edges = sorted(
        {
            left,
            right,
            *(edge for rect in clipped for edge in (rect.x(), rect.x() + rect.width())),
        }
    )
    for start, end in pairwise(x_edges):
        if end - start <= tolerance:
            continue
        sample_x = (start + end) / 2.0
        intervals = sorted(
            (rect.y(), rect.y() + rect.height())
            for rect in clipped
            if rect.x() <= sample_x + tolerance
            and rect.x() + rect.width() >= sample_x - tolerance
        )
        if not intervals or intervals[0][0] > top + tolerance:
            return False
        covered_bottom = intervals[0][1]
        for interval_top, interval_bottom in intervals[1:]:
            if interval_top > covered_bottom + tolerance:
                break
            covered_bottom = max(covered_bottom, interval_bottom)
        if covered_bottom < bottom - tolerance:
            return False
    return True


__all__ = ["rectangles_cover"]
