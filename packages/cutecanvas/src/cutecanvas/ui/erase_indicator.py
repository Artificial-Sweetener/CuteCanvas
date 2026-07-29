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

"""Render one reusable erase-mode decoration over editor feedback."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPen


class EraseIndicatorRenderer:
    """Overlay the canonical high-contrast erase glyph on any feedback bounds."""

    def draw(self, painter: QPainter, bounds: QRectF) -> None:
        """Draw the brush-established underscore glyph within logical bounds.

        Qt scales the point-sized glyph through the paint device transform, so
        the same logical geometry produces a crisp marker at every device pixel
        ratio.
        """
        extent = max(1.0, min(bounds.width(), bounds.height()))
        font = painter.font()
        font.setPointSize(max(4, int(extent * 0.3)))
        painter.save()
        try:
            painter.setFont(font)
            painter.translate(
                bounds.x() + (extent * 0.15),
                bounds.y() + (extent * 0.1),
            )
            padding = int(extent * 0.1)
            text_rect = QRectF(
                padding,
                padding,
                extent - (padding * 2),
                extent - (padding * 2),
            )
            painter.setPen(QPen(Qt.GlobalColor.black))
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
                "_",
            )
            painter.setPen(QPen(Qt.GlobalColor.white))
            painter.drawText(
                text_rect.translated(-1.0, -1.0),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
                "_",
            )
        finally:
            painter.restore()


__all__ = ["EraseIndicatorRenderer"]
