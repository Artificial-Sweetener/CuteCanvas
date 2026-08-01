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
"""Decide whether derived raster products can survive cache admission."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QImage

CacheAdmissionGuard = Callable[[int], bool]


def cache_admits_bytes(
    size_bytes: int,
    *,
    configured_limit_bytes: int,
    externally_managed: bool,
    guard: CacheAdmissionGuard | None,
) -> bool:
    """Return whether one product can be retained under current cache policy."""
    size = max(0, int(size_bytes))
    limit = max(0, int(configured_limit_bytes))
    if not externally_managed and size > limit:
        return False
    return guard is None or guard(size)


def estimated_image_region_bytes(image: QImage, width: int, height: int) -> int:
    """Return QImage's aligned storage estimate for one cropped region."""
    if image.isNull() or width <= 0 or height <= 0:
        return 0
    bits_per_line = max(1, int(width)) * max(1, int(image.depth()))
    bytes_per_line = ((bits_per_line + 31) // 32) * 4
    return bytes_per_line * max(1, int(height))


def estimated_pyramid_bytes(image: QImage, min_view_size_px: int) -> int:
    """Return the retained bytes produced by QPane's pyramid generator."""
    if image.isNull():
        return 0
    width = image.width()
    height = image.height()
    minimum = max(1, int(min_view_size_px))
    total = int(image.sizeInBytes())
    scale = 1.0
    level_width = width
    level_height = height
    while max(level_width, level_height) > minimum:
        scale /= 2.0
        level_width = int(width * scale)
        level_height = int(height * scale)
        if level_width <= 0 or level_height <= 0:
            break
        total += level_width * level_height * 4
    return total


__all__ = [
    "CacheAdmissionGuard",
    "cache_admits_bytes",
    "estimated_image_region_bytes",
    "estimated_pyramid_bytes",
]
