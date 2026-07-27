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

"""Assign disjoint output coverage to overlapping raster tile products."""

from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtGui import QRegion

from ..scene.render_plan import TileRenderData


def tile_output_rect(
    tile: TileRenderData,
    source_rect: QRect,
    overlap: int,
) -> QRect:
    """Return the non-overlapping source region owned by one ready tile."""
    tile_x = round(tile.draw_pos.x())
    tile_y = round(tile.draw_pos.y())
    left = tile_x + (overlap if tile_x > source_rect.x() else 0)
    top = tile_y + (overlap if tile_y > source_rect.y() else 0)
    right = min(
        source_rect.x() + source_rect.width(),
        tile_x + tile.image.width(),
    )
    bottom = min(
        source_rect.y() + source_rect.height(),
        tile_y + tile.image.height(),
    )
    return QRect(left, top, max(0, right - left), max(0, bottom - top))


def fallback_output_region(
    source_rect: QRect,
    tile_rects: tuple[QRect, ...],
) -> QRegion:
    """Return source coverage not owned by any ready tile."""
    fallback = QRegion(source_rect)
    for tile_rect in tile_rects:
        if not tile_rect.isEmpty():
            fallback -= QRegion(tile_rect)
    return fallback
