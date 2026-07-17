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

"""Cursor factories for brush and smart select tools."""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QCursor, QImage, QPainter, QPen, QPixmap

from .brush_feedback import BRUSH_OUTLINE_PADDING, draw_brush_outline


class CursorBuilder:
    """Cache-aware factory for QPane's brush and smart select cursors."""

    def __init__(self) -> None:
        """Initialize per-shape cursor caches for reuse across tool sessions."""
        self._brush_cursor_cache: dict[tuple, tuple[QCursor, QCursor]] = {}
        self._smart_cursor_cache: dict[tuple, QCursor] = {}

    def clear_cache(self) -> None:
        """Drop all cached cursors so the next request rerenders them."""
        self._brush_cursor_cache.clear()
        self._smart_cursor_cache.clear()

    def get_brush_cursor_pair(
        self, size: int, color: QColor
    ) -> tuple[QCursor, QCursor]:
        """Return the cached paint/erase cursors for the requested brush.

        Args:
            size: Diameter of the brush outline in device pixels.
            color: Outline color used to render the cursor.

        Returns:
            Tuple of (paint_cursor, erase_cursor) for the requested size/color.
        """
        return self._ensure_brush_cursor_pair(size, color)

    def create_brush_cursor(
        self, size: int, color: QColor, erase_indicator: bool = False
    ) -> QCursor:
        """Return a circular brush cursor, optionally decorated with the erase indicator.

        Args:
            size: Diameter of the brush outline in device pixels.
            color: Outline color for the cursor ring.
            erase_indicator: Draw the erase marker when True.

        Returns:
            Cached cursor matching the requested configuration.
        """
        paint_cursor, erase_cursor = self._ensure_brush_cursor_pair(size, color)
        return erase_cursor if erase_indicator else paint_cursor

    def create_smart_select_cursor(self, erase_indicator: bool = False) -> QCursor:
        """Return the cached smart select crosshair cursor.

        Args:
            erase_indicator: Draw the erase marker inside the crosshair when True.

        Returns:
            Cached crosshair cursor configured with the erase indicator flag.
        """
        cursor_size = 32
        line_gap = 5
        outline_width = 4
        inset = outline_width / 2  # Keep the stroke inside the cursor image
        cache_key = (
            "smart_select_crosshair_inset",
            cursor_size,
            line_gap,
            outline_width,
            erase_indicator,
        )
        cached_cursor = self._smart_cursor_cache.get(cache_key)
        if cached_cursor is not None:
            return cached_cursor
        cursor_image = QImage(
            QSize(cursor_size, cursor_size), QImage.Format_ARGB32_Premultiplied
        )
        cursor_image.fill(Qt.transparent)
        painter = QPainter(cursor_image)
        painter.setRenderHint(QPainter.Antialiasing, True)
        hotspot = cursor_size // 2
        hotspot_float = float(hotspot)
        gap_float = float(line_gap)
        outline_pen = QPen(Qt.white)
        outline_pen.setWidth(outline_width)
        self._draw_crosshair_lines(
            painter, outline_pen, hotspot_float, gap_float, cursor_size, inset
        )
        foreground_pen = QPen(Qt.black)
        foreground_pen.setWidth(2)
        self._draw_crosshair_lines(
            painter, foreground_pen, hotspot_float, gap_float, cursor_size, inset
        )
        if erase_indicator:
            self._draw_erase_indicator(painter, cursor_size)
        painter.end()
        cursor_pixmap = QPixmap.fromImage(cursor_image)
        cursor = QCursor(cursor_pixmap, hotspot, hotspot)
        self._smart_cursor_cache[cache_key] = cursor
        return cursor

    def _ensure_brush_cursor_pair(
        self, size: int, color: QColor
    ) -> tuple[QCursor, QCursor]:
        """Cache and return the paint/erase cursors for the requested size and color."""
        size = max(3, int(size))
        cache_key = ("brush", size, color.rgb())
        cached = self._brush_cursor_cache.get(cache_key)
        if cached is not None:
            return cached
        paint_cursor = self._render_brush_cursor(size, color, erase_indicator=False)
        erase_cursor = self._render_brush_cursor(size, color, erase_indicator=True)
        pair = (paint_cursor, erase_cursor)
        self._brush_cursor_cache[cache_key] = pair
        return pair

    def _render_brush_cursor(
        self, size: int, color: QColor, *, erase_indicator: bool
    ) -> QCursor:
        """Render a circular brush cursor image and wrap it in a QCursor."""
        border = BRUSH_OUTLINE_PADDING
        canvas_size = size + (border * 2)
        cursor_image = QImage(
            QSize(canvas_size, canvas_size), QImage.Format_ARGB32_Premultiplied
        )
        cursor_image.fill(Qt.transparent)
        painter = QPainter(cursor_image)
        painter.setRenderHint(QPainter.Antialiasing, True)
        ellipse_diameter = size - 1
        top_left = float(border) + 0.5
        draw_brush_outline(
            painter,
            QRectF(top_left, top_left, ellipse_diameter, ellipse_diameter),
            color,
        )
        if erase_indicator:
            self._draw_erase_indicator(painter, size, origin_offset=float(border))
        painter.end()
        cursor_pixmap = QPixmap.fromImage(cursor_image)
        hotspot = border + (size // 2)
        return QCursor(cursor_pixmap, hotspot, hotspot)

    def _draw_crosshair_lines(
        self,
        painter: QPainter,
        pen: QPen,
        hotspot: float,
        gap: float,
        size: int,
        inset: float,
    ) -> None:
        """Draw the four crosshair segments for the smart select cursor."""
        painter.setPen(pen)
        size_float = float(size)
        top_start = QPointF(hotspot, inset)
        top_end = QPointF(hotspot, hotspot - gap)
        bottom_start = QPointF(hotspot, hotspot + gap)
        bottom_end = QPointF(hotspot, size_float - inset)
        left_start = QPointF(inset, hotspot)
        left_end = QPointF(hotspot - gap, hotspot)
        right_start = QPointF(hotspot + gap, hotspot)
        right_end = QPointF(size_float - inset, hotspot)
        painter.drawLine(top_start, top_end)
        painter.drawLine(bottom_start, bottom_end)
        painter.drawLine(left_start, left_end)
        painter.drawLine(right_start, right_end)

    def _draw_erase_indicator(
        self, painter: QPainter, size: int, *, origin_offset: float = 0.0
    ) -> None:
        """Draw the high-contrast "-" indicator onto the cursor image."""
        font = painter.font()
        font.setPointSize(max(4, int(size * 0.3)))
        painter.setFont(font)
        painter.save()
        x_offset = size * 0.15
        y_offset = size * 0.1
        painter.translate(origin_offset + x_offset, origin_offset + y_offset)
        padding = int(size * 0.1)
        text_rect = QRectF(padding, padding, size - (padding * 2), size - (padding * 2))
        painter.setPen(QPen(Qt.black))
        painter.drawText(text_rect, Qt.AlignRight | Qt.AlignBottom, "_")
        white_text_rect = text_rect.translated(-1, -1)
        painter.setPen(QPen(Qt.white))
        painter.drawText(white_text_rect, Qt.AlignRight | Qt.AlignBottom, "_")
        painter.restore()
