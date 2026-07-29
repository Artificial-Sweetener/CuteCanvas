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

"""Build DPR-aware base cursors with shared modifier decoration."""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QCursor, QImage, QPainter, QPen, QPixmap

from .brush_feedback import draw_brush_outline
from .erase_indicator import EraseIndicatorRenderer

_CURSOR_COMPOSITION_PADDING = 4


class CursorBuilder:
    """Cache-aware factory for CuteCanvas's editor feedback cursors."""

    def __init__(
        self,
        erase_indicator: EraseIndicatorRenderer | None = None,
    ) -> None:
        """Initialize cursor caches and the shared modifier decorator."""
        self._brush_cursor_cache: dict[tuple, tuple[QCursor, QCursor]] = {}
        self._precision_cursor_cache: dict[tuple, QCursor] = {}
        self._erase_indicator = erase_indicator or EraseIndicatorRenderer()

    def clear_cache(self) -> None:
        """Drop all cached cursors so the next request rerenders them."""
        self._brush_cursor_cache.clear()
        self._precision_cursor_cache.clear()

    def get_brush_cursor_pair(
        self,
        size: int,
        color: QColor,
        *,
        device_pixel_ratio: float = 1.0,
    ) -> tuple[QCursor, QCursor]:
        """Return the cached paint/erase cursors for the requested brush.

        Args:
            size: Diameter of the brush outline in device pixels.
            color: Outline color used to render the cursor.
            device_pixel_ratio: Physical pixels represented by one logical pixel.

        Returns:
            Tuple of (paint_cursor, erase_cursor) for the requested size/color.
        """
        return self._ensure_brush_cursor_pair(size, color, device_pixel_ratio)

    def create_brush_cursor(
        self,
        size: int,
        color: QColor,
        erase_indicator: bool = False,
        *,
        device_pixel_ratio: float = 1.0,
    ) -> QCursor:
        """Return a circular brush cursor, optionally decorated with the erase indicator.

        Args:
            size: Diameter of the brush outline in device pixels.
            color: Outline color for the cursor ring.
            erase_indicator: Draw the erase marker when True.
            device_pixel_ratio: Physical pixels represented by one logical pixel.

        Returns:
            Cached cursor matching the requested configuration.
        """
        paint_cursor, erase_cursor = self._ensure_brush_cursor_pair(
            size,
            color,
            device_pixel_ratio,
        )
        return erase_cursor if erase_indicator else paint_cursor

    def create_precision_cursor(
        self,
        erase_indicator: bool = False,
        *,
        device_pixel_ratio: float = 1.0,
    ) -> QCursor:
        """Return the cached precise coverage crosshair cursor.

        Args:
            erase_indicator: Draw the erase marker inside the crosshair when True.
            device_pixel_ratio: Physical pixels represented by one logical pixel.

        Returns:
            Cached crosshair cursor configured with the erase indicator flag.
        """
        cursor_size = 32
        border = _CURSOR_COMPOSITION_PADDING
        canvas_size = cursor_size + (border * 2)
        line_gap = 5
        outline_width = 4
        inset = outline_width / 2  # Keep the stroke inside the cursor image
        dpr = self._normalized_dpr(device_pixel_ratio)
        cache_key = (
            "smart_select_crosshair_inset",
            cursor_size,
            border,
            line_gap,
            outline_width,
            erase_indicator,
            dpr,
        )
        cached_cursor = self._precision_cursor_cache.get(cache_key)
        if cached_cursor is not None:
            return cached_cursor
        cursor_image = self._cursor_image(canvas_size, canvas_size, dpr)
        cursor_image.fill(Qt.transparent)
        painter = QPainter(cursor_image)
        painter.setRenderHint(QPainter.Antialiasing, True)
        hotspot = border + (cursor_size // 2)
        hotspot_float = float(cursor_size // 2)
        gap_float = float(line_gap)
        outline_pen = QPen(Qt.white)
        outline_pen.setWidth(outline_width)
        painter.translate(float(border), float(border))
        self._draw_crosshair_lines(
            painter, outline_pen, hotspot_float, gap_float, cursor_size, inset
        )
        foreground_pen = QPen(Qt.black)
        foreground_pen.setWidth(2)
        self._draw_crosshair_lines(
            painter, foreground_pen, hotspot_float, gap_float, cursor_size, inset
        )
        if erase_indicator:
            self._erase_indicator.draw(
                painter,
                QRectF(0.0, 0.0, float(cursor_size), float(cursor_size)),
            )
        painter.end()
        cursor_pixmap = QPixmap.fromImage(cursor_image)
        cursor = QCursor(cursor_pixmap, hotspot, hotspot)
        self._precision_cursor_cache[cache_key] = cursor
        return cursor

    def _ensure_brush_cursor_pair(
        self,
        size: int,
        color: QColor,
        device_pixel_ratio: float,
    ) -> tuple[QCursor, QCursor]:
        """Cache and return the paint/erase cursors for the requested size and color."""
        size = max(3, int(size))
        dpr = self._normalized_dpr(device_pixel_ratio)
        cache_key = ("brush", size, color.rgb(), dpr)
        cached = self._brush_cursor_cache.get(cache_key)
        if cached is not None:
            return cached
        paint_cursor = self._render_brush_cursor(
            size,
            color,
            erase_indicator=False,
            device_pixel_ratio=dpr,
        )
        erase_cursor = self._render_brush_cursor(
            size,
            color,
            erase_indicator=True,
            device_pixel_ratio=dpr,
        )
        pair = (paint_cursor, erase_cursor)
        self._brush_cursor_cache[cache_key] = pair
        return pair

    def _render_brush_cursor(
        self,
        size: int,
        color: QColor,
        *,
        erase_indicator: bool,
        device_pixel_ratio: float,
    ) -> QCursor:
        """Render a circular brush cursor image and wrap it in a QCursor."""
        border = _CURSOR_COMPOSITION_PADDING
        canvas_size = size + (border * 2)
        cursor_image = self._cursor_image(
            canvas_size,
            canvas_size,
            device_pixel_ratio,
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
            self._erase_indicator.draw(
                painter,
                QRectF(float(border), float(border), float(size), float(size)),
            )
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

    @staticmethod
    def _normalized_dpr(device_pixel_ratio: float) -> float:
        """Return a stable positive device ratio suitable for raster caching."""
        return round(max(0.01, float(device_pixel_ratio)), 6)

    @staticmethod
    def _cursor_image(width: int, height: int, dpr: float) -> QImage:
        """Create a transparent high-DPI image with logical painter coordinates."""
        image = QImage(
            QSize(round(width * dpr), round(height * dpr)),
            QImage.Format_ARGB32_Premultiplied,
        )
        image.setDevicePixelRatio(dpr)
        return image
