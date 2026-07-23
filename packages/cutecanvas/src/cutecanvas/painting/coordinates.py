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

"""Brush-coordinate continuity across mutable raster storage origins."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .model import BrushStrokeSegment


@dataclass(slots=True)
class BrushSourceCoordinateSession:
    """Map zero-origin source samples into stable layer-local coordinates."""

    previous_origin: tuple[float, float]

    def layer_segment(
        self,
        segment: BrushStrokeSegment,
        current_origin: tuple[float, float],
    ) -> BrushStrokeSegment:
        """Return one continuous segment and retain its endpoint origin."""
        start_origin = self.previous_origin
        end_origin = (float(current_origin[0]), float(current_origin[1]))
        self.previous_origin = end_origin
        return replace(
            segment,
            start=(
                float(segment.start[0]) + start_origin[0],
                float(segment.start[1]) + start_origin[1],
            ),
            end=(
                float(segment.end[0]) + end_origin[0],
                float(segment.end[1]) + end_origin[1],
            ),
        )
