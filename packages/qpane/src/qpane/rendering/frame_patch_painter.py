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
"""Canonical physical-patch painting for overscanned widget surfaces."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QRegion

from .coordinates import CoordinateContext

if TYPE_CHECKING:
    from ..viewer import QPane


class FramePatchPainter:
    """Map physical backing patches through one widget coordinate system."""

    def __init__(
        self,
        qpane: QPane,
        margin_provider: Callable[[], int],
    ) -> None:
        """Bind the target widget and its dynamic physical overscan margin."""
        self._qpane = qpane
        self._margin_provider = margin_provider

    def paint(
        self,
        painter: QPainter,
        physical_rects: tuple[QRect, ...] | list[QRect],
        draw: Callable[[QPainter, tuple[QRectF, ...]], None],
    ) -> None:
        """Clear and recompose disjoint physical patches in widget coordinates."""
        context = CoordinateContext(self._qpane)
        margin = self.margin_logical(context)
        buffer_clips: list[QRectF] = []
        panel_clips: list[QRectF] = []
        for rect in physical_rects:
            if rect.isEmpty():
                continue
            buffer_clip = context.physical_to_logical(QRectF(rect))
            if not isinstance(buffer_clip, QRectF):
                raise TypeError("physical rectangle conversion must return QRectF")
            buffer_clips.append(buffer_clip)
            panel_clips.append(self.panel_rect(QRectF(rect), context))
        if not buffer_clips:
            return
        clip_path = QPainterPath()
        clip_path.setFillRule(Qt.FillRule.WindingFill)
        for buffer_clip in buffer_clips:
            clip_path.addRect(buffer_clip)
        painter.save()
        try:
            painter.setClipPath(clip_path, Qt.ClipOperation.IntersectClip)
            painter.setCompositionMode(QPainter.CompositionMode_Source)
            for buffer_clip in buffer_clips:
                painter.fillRect(buffer_clip, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.translate(margin)
            draw(painter, tuple(panel_clips))
        finally:
            painter.restore()

    def logical_region(
        self,
        physical_rects: tuple[QRect, ...] | list[QRect],
    ) -> QRegion:
        """Return widget-logical coverage for physical backing rectangles."""
        context = CoordinateContext(self._qpane)
        region = QRegion()
        for rect in physical_rects:
            region += self.panel_rect(QRectF(rect), context).toAlignedRect()
        return region

    def panel_rect(
        self,
        physical_rect: QRectF,
        context: CoordinateContext | None = None,
    ) -> QRectF:
        """Map a physical backing rectangle into widget-logical coordinates."""
        coordinates = context or CoordinateContext(self._qpane)
        margin = float(self._margin_provider())
        viewport_rect = QRectF(
            physical_rect.x() - margin,
            physical_rect.y() - margin,
            physical_rect.width(),
            physical_rect.height(),
        )
        logical = coordinates.physical_to_logical(viewport_rect)
        if not isinstance(logical, QRectF):
            raise TypeError("physical rectangle conversion must return QRectF")
        return logical

    def margin_logical(
        self,
        context: CoordinateContext | None = None,
    ) -> QPointF:
        """Return the overscan margin in widget-logical units."""
        coordinates = context or CoordinateContext(self._qpane)
        margin = float(self._margin_provider())
        logical = coordinates.physical_to_logical(QPointF(margin, margin))
        if not isinstance(logical, QPointF):
            raise TypeError("physical point conversion must return QPointF")
        return logical
