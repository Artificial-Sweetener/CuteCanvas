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

"""Overlay example that frames the viewport and labels zoom via OverlayState."""

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient

# Provided by the demo host at execution time:
# - state: OverlayState (stable overlay snapshot)


def draw_overlay(painter, state):
    """Paint a gradient frame registered via QPane.registerOverlay.

    QPane calls this hook during overlay repaints with an OverlayState snapshot.
    """
    painter.save()
    margin = 12
    frame_rect = state.qpane_rect.adjusted(margin, margin, -margin, -margin)
    gradient = QLinearGradient(frame_rect.topLeft(), frame_rect.bottomRight())
    gradient.setColorAt(0.0, QColor(255, 99, 71, 40))
    gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.setBrush(gradient)
    pen = QColor(255, 99, 71)
    pen.setAlpha(180)
    painter.setPen(pen)
    painter.drawRoundedRect(frame_rect, 8, 8)
    zoom_label = f"Zoom: {state.zoom * 100:.0f}%"
    painter.setFont(QFont("Arial", 10, QFont.Weight.DemiBold))
    painter.drawText(
        QRect(frame_rect.left() + 8, frame_rect.top(), frame_rect.width(), 32),
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        zoom_label,
    )
    painter.restore()
