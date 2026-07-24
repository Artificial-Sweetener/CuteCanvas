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
"""DPR-stable reveal geometry for two independent render targets."""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QLineF, QRectF

from ..types import ComparisonOrientation


@dataclass(frozen=True, slots=True)
class TargetComparisonSnapshot:
    """Describe exact primary, secondary, and divider geometry."""

    viewport: QRectF
    primary_clip: QRectF
    secondary_clip: QRectF
    divider: QLineF
    split_position: float
    orientation: ComparisonOrientation
    device_pixel_ratio: float


class TargetComparisonLayout:
    """Project one normalized reveal split on a physical-pixel boundary."""

    def arrange(
        self,
        viewport: QRectF,
        *,
        split_position: float,
        orientation: ComparisonOrientation = ComparisonOrientation.VERTICAL,
        device_pixel_ratio: float = 1.0,
    ) -> TargetComparisonSnapshot:
        """Return logical clips whose shared edge is one physical boundary."""
        if not isinstance(viewport, QRectF):
            raise TypeError("viewport must be a QRectF")
        if viewport.width() < 0.0 or viewport.height() < 0.0:
            raise ValueError("viewport dimensions must be non-negative")
        split = float(split_position)
        if not math.isfinite(split) or not 0.0 <= split <= 1.0:
            raise ValueError("split_position must be finite and between zero and one")
        dpr = float(device_pixel_ratio)
        if not math.isfinite(dpr) or dpr <= 0.0:
            raise ValueError("device_pixel_ratio must be positive and finite")
        resolved_orientation = ComparisonOrientation(orientation)
        if resolved_orientation is ComparisonOrientation.VERTICAL:
            physical_extent = round(viewport.width() * dpr)
            offset = round(physical_extent * split) / dpr
            boundary = viewport.x() + offset
            primary = QRectF(
                viewport.x(),
                viewport.y(),
                offset,
                viewport.height(),
            )
            secondary = QRectF(
                boundary,
                viewport.y(),
                max(0.0, viewport.width() - offset),
                viewport.height(),
            )
            divider = QLineF(
                boundary,
                viewport.top(),
                boundary,
                viewport.bottom(),
            )
        else:
            physical_extent = round(viewport.height() * dpr)
            offset = round(physical_extent * split) / dpr
            boundary = viewport.y() + offset
            primary = QRectF(
                viewport.x(),
                viewport.y(),
                viewport.width(),
                offset,
            )
            secondary = QRectF(
                viewport.x(),
                boundary,
                viewport.width(),
                max(0.0, viewport.height() - offset),
            )
            divider = QLineF(
                viewport.left(),
                boundary,
                viewport.right(),
                boundary,
            )
        return TargetComparisonSnapshot(
            QRectF(viewport),
            primary,
            secondary,
            divider,
            split,
            resolved_orientation,
            dpr,
        )
