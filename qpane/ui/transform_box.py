#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Stateless Qt presentation for the affine transform box."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF

from ..scene.transform_geometry import TransformHandle

if TYPE_CHECKING:
    from ..editor.transform_interaction import TransformBoxPresentation

_HANDLE_RADIUS = 4.0


class TransformBoxRenderer:
    """Draw a restrained outline and eight circular panel-space handles."""

    def draw(
        self,
        painter: QPainter,
        state: TransformBoxPresentation | None,
        hovered_handle: TransformHandle | None,
    ) -> None:
        """Draw current transform feedback without retaining editor state."""
        if state is None:
            return
        painter.save()
        outline = QColor(82, 139, 205, 225)
        pen = QPen(outline, 1.0, Qt.PenStyle.SolidLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolygon(QPolygonF(state.corners))
        for handle, point in state.handles:
            radius = _HANDLE_RADIUS + (1.0 if handle is hovered_handle else 0.0)
            painter.setBrush(QColor(238, 242, 247, 245))
            painter.drawEllipse(point, radius, radius)
        painter.restore()
