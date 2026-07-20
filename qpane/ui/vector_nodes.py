#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Panel-space presentation for detached vector node-edit feedback."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from ..vector.node_edit import VectorNodeOverlayState
from ..vector.public import VectorNodeRole


class VectorNodeOverlayRenderer:
    """Draw selected paths and control handles without editor state."""

    def draw(self, painter: QPainter, state: object | None) -> None:
        """Render one detached node overlay when available."""
        if not isinstance(state, VectorNodeOverlayState):
            return
        painter.save()
        try:
            outline = QPen(QColor(75, 155, 225, 230), 1.0)
            outline.setCosmetic(True)
            painter.setPen(outline)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(state.path)
            for handle in state.handles:
                selected = handle.index == state.selected_index
                painter.setPen(QPen(QColor(245, 245, 245), 1.0))
                painter.setBrush(
                    QColor(245, 245, 245) if selected else QColor(45, 105, 165)
                )
                radius = 3.5 if handle.role is not VectorNodeRole.CONTROL else 3.0
                rectangle = QRectF(
                    handle.point.x() - radius,
                    handle.point.y() - radius,
                    radius * 2.0,
                    radius * 2.0,
                )
                if handle.role is VectorNodeRole.CONTROL:
                    painter.drawEllipse(rectangle)
                else:
                    painter.drawRect(rectangle)
        finally:
            painter.restore()
