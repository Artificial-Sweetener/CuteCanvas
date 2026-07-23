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
"""Coordinate-scale conversion for device-pixel snapping thresholds."""

from __future__ import annotations

import math


def scene_units_per_device_pixel(viewport_zoom: float) -> float:
    """Return scene units represented by one physical viewport pixel.

    QPane's authoritative viewport zoom is defined in physical device pixels.
    Qt pointer positions are logical pixels, but snapping compares scene-space
    geometry against a physical-pixel tolerance, so the widget DPR must not be
    applied a second time here.

    Args:
        viewport_zoom: QPane viewport zoom in physical pixels per scene unit.

    Returns:
        Scene units represented by one physical viewport pixel.

    Raises:
        ValueError: If ``viewport_zoom`` is not finite and positive.
    """
    zoom = float(viewport_zoom)
    if not math.isfinite(zoom) or zoom <= 0.0:
        raise ValueError("viewport zoom must be finite and positive")
    return 1.0 / zoom
