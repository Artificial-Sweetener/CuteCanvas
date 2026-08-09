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
"""Stateless Qt presentation for the affine transform box."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from qpane.sdk.scene import TransformHandle

from .affine_handles import draw_affine_handle

if TYPE_CHECKING:
    from ..editor.transform_interaction import TransformBoxPresentation


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
            draw_affine_handle(
                painter,
                point,
                emphasized=handle is hovered_handle,
            )
        painter.restore()
