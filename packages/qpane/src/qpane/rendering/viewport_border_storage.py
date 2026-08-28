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
"""Build checked native storage for rounded viewport-border presentation."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPixmap

from .storage_allocation import checked_painter, checked_pixmap


def build_viewport_border_storage(
    viewport_rect: QRectF,
    radius: float,
    border_rects: tuple[QRect, ...],
) -> tuple[tuple[QPixmap, ...], tuple[QPixmap, ...]]:
    """Return antialiased alpha masks and transparent composition buffers."""
    rounded_path = QPainterPath()
    rounded_path.addRoundedRect(viewport_rect, radius, radius)
    masks: list[QPixmap] = []
    buffers: list[QPixmap] = []
    for border_rect in border_rects:
        mask = checked_pixmap(border_rect.size())
        mask.fill(Qt.GlobalColor.transparent)
        opaque = checked_pixmap(border_rect.size())
        opaque.fill(Qt.GlobalColor.white)
        mask_painter = checked_painter(mask, "viewport border mask")
        try:
            mask_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            mask_painter.setClipPath(
                rounded_path.translated(
                    -border_rect.left(),
                    -border_rect.top(),
                )
            )
            mask_painter.drawPixmap(QPoint(), opaque)
        finally:
            mask_painter.end()
        masks.append(mask)
        buffer = checked_pixmap(border_rect.size())
        buffer.fill(Qt.GlobalColor.transparent)
        buffers.append(buffer)
    return tuple(masks), tuple(buffers)


__all__ = ["build_viewport_border_storage"]
