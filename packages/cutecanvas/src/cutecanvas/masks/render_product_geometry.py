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
"""Map sparse storage damage into source-aligned mask render products."""

from __future__ import annotations

from PySide6.QtCore import QRect

from qpane.sdk.scene import RasterBounds


def storage_damage_destination(
    storage_bounds: RasterBounds | None,
    source_bounds: RasterBounds | None,
    storage_rect: QRect,
    scale: float,
) -> QRect | None:
    """Return cache-product pixels corresponding to storage-relative damage."""
    if storage_bounds is None or source_bounds is None:
        return None
    source_rect = QRect(
        storage_bounds.x + storage_rect.x() - source_bounds.x,
        storage_bounds.y + storage_rect.y() - source_bounds.y,
        storage_rect.width(),
        storage_rect.height(),
    )
    return scaled_source_rect(source_rect, scale)


def scaled_source_rect(source_rect: QRect, scale: float) -> QRect:
    """Project source endpoints onto one shared scaled-pixel lattice."""
    left = round(source_rect.left() * scale)
    top = round(source_rect.top() * scale)
    right = round((source_rect.right() + 1) * scale)
    bottom = round((source_rect.bottom() + 1) * scale)
    return QRect(left, top, max(1, right - left), max(1, bottom - top))


__all__ = ["scaled_source_rect", "storage_damage_destination"]
