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
"""Canonical finite raster aperture for editable composition scenes."""

from __future__ import annotations

from math import ceil, floor

from qpane.sdk.scene import RasterBounds, SceneDescriptor


def scene_raster_bounds(scene: SceneDescriptor) -> RasterBounds | None:
    """Return integer canvas bounds for one finite scene descriptor."""
    left = floor(scene.bounds.x)
    top = floor(scene.bounds.y)
    right = ceil(scene.bounds.x + scene.bounds.width)
    bottom = ceil(scene.bounds.y + scene.bounds.height)
    if right <= left or bottom <= top:
        return None
    return RasterBounds(left, top, right - left, bottom - top)


__all__ = ["scene_raster_bounds"]
