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
"""Geometry policy shared by composition-facing editor facades."""

from PySide6.QtCore import QRectF, QSize


def aspect_scene_rect(
    source_size: QSize,
    target_rect: QRectF,
    *,
    cover: bool,
) -> QRectF:
    """Return an aspect-preserving rectangle centered on ``target_rect``."""
    source_width = float(source_size.width())
    source_height = float(source_size.height())
    if source_width <= 0.0 or source_height <= 0.0:
        raise ValueError("source_size dimensions must be positive")
    target = QRectF(target_rect)
    target_width = float(target.width())
    target_height = float(target.height())
    if target_width < 0.0 or target_height < 0.0:
        raise ValueError("target_rect dimensions must be non-negative")
    center = target.center()
    if target_width == 0.0 or target_height == 0.0:
        return QRectF(center.x(), center.y(), 0.0, 0.0)
    source_aspect = source_width / source_height
    target_aspect = target_width / target_height
    use_target_width = (
        target_aspect > source_aspect if cover else target_aspect <= source_aspect
    )
    if use_target_width:
        width = target_width
        height = width / source_aspect
    else:
        height = target_height
        width = height * source_aspect
    return QRectF(
        center.x() - width / 2.0,
        center.y() - height / 2.0,
        width,
        height,
    )
