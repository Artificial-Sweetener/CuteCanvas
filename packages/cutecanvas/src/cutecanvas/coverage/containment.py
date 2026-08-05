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
"""Point containment for evaluated coverage snapshots."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF

from .surface import CoverageSnapshot


def coverage_contains(coverage: CoverageSnapshot, point: QPointF) -> bool:
    """Return whether ``point`` lies inside nonzero evaluated coverage."""
    bounds = coverage.bounds
    if bounds is None:
        return False
    x = math.floor(point.x())
    y = math.floor(point.y())
    if x < bounds.x or y < bounds.y or x >= bounds.right or y >= bounds.bottom:
        return False
    return bool(coverage.pixels[y - bounds.y, x - bounds.x])
