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

"""Stateless panel renderer for shared-edge resize feedback."""

from __future__ import annotations

from cutecanvas.editor.shared_edge_pivot import SharedEdgeHandle
from cutecanvas.editor.shared_edge_presentation import SharedEdgePresentation
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen

from .affine_handles import draw_affine_handle


class SharedEdgeRenderer:
    """Draw inferred shared seams and handles without owning state."""

    def draw(
        self,
        painter: QPainter,
        presentation: SharedEdgePresentation | None,
    ) -> None:
        """Draw every shared edge and its three manipulation handles."""
        if presentation is None:
            return
        painter.save()
        for edge in presentation.edges:
            focused = edge.active or edge.hovered
            seam = QPen(
                QColor(82, 139, 205, 245 if focused else 190),
                2.0 if focused else 1.0,
                Qt.PenStyle.SolidLine,
            )
            seam.setCosmetic(True)
            painter.setPen(seam)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(edge.start, edge.end)
            start, middle, end = edge.handles
            draw_affine_handle(
                painter,
                start,
                emphasized=(focused and edge.focused_handle is SharedEdgeHandle.START),
                enabled=edge.start_enabled,
            )
            draw_affine_handle(
                painter,
                middle,
                emphasized=focused,
                enabled=edge.middle_enabled,
            )
            draw_affine_handle(
                painter,
                end,
                emphasized=focused and edge.focused_handle is SharedEdgeHandle.END,
                enabled=edge.end_enabled,
            )
        painter.restore()


__all__ = ["SharedEdgeRenderer"]
