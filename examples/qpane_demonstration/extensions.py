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
"""Small public-extension examples for the QPane viewer demo."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QMouseEvent, QPainter, QPen
from qpane import QPane, ViewerTool


class InspectionTool(ViewerTool):
    """Show restrained source-coordinate feedback under the pointer."""

    def __init__(self, pane: QPane) -> None:
        """Retain the public viewer facade used for coordinate projection."""
        super().__init__()
        self._pane = pane
        self._position: QPointF | None = None

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Track pointer location and request one tool-overlay repaint."""
        self._position = QPointF(event.position())
        self.signals.repaint_overlay_requested.emit()
        event.accept()

    def leaveEvent(self, event: object) -> None:
        """Clear feedback when the pointer leaves the viewer."""
        del event
        self._position = None
        self.signals.repaint_overlay_requested.emit()

    def draw_overlay(self, painter: QPainter) -> None:
        """Draw a compact crosshair and projected scene coordinate."""
        position = self._position
        if position is None:
            return
        hit = self._pane.panelHitTest(position)
        if hit is None:
            return
        scene_point = hit.raw_point
        painter.save()
        painter.setPen(QPen(QColor(112, 204, 255, 220), 1.0))
        painter.drawEllipse(position, 8.0, 8.0)
        painter.drawLine(
            position + QPointF(-13.0, 0.0),
            position + QPointF(13.0, 0.0),
        )
        painter.drawLine(
            position + QPointF(0.0, -13.0),
            position + QPointF(0.0, 13.0),
        )
        painter.drawText(
            position + QPointF(16.0, -10.0),
            f"{scene_point.x():.0f}, {scene_point.y():.0f}",
        )
        painter.restore()

    def getCursor(self) -> QCursor:
        """Return the familiar precision crosshair cursor."""
        return QCursor(Qt.CursorShape.CrossCursor)


def draw_viewer_frame(painter: QPainter, state: object) -> None:
    """Frame the visible canvas using the public content-overlay state."""
    qpane_rect = getattr(state, "qpane_rect", None)
    zoom = getattr(state, "zoom", None)
    if qpane_rect is None or zoom is None:
        return
    frame = QRectF(qpane_rect).adjusted(12.0, 12.0, -12.0, -12.0)
    painter.save()
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(112, 204, 255, 150), 1.0))
    painter.drawRoundedRect(frame, 7.0, 7.0)
    painter.drawText(
        frame.topLeft() + QPointF(8.0, 18.0),
        f"{float(zoom) * 100:.1f}%",
    )
    painter.restore()
