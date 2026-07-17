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

"""Brush preview value state and canvas rendering."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from qpane.tools.input.model import PointerDeviceKind
from qpane.ui.brush_feedback import draw_brush_outline


@dataclass(frozen=True, slots=True)
class BrushPreview:
    """Describe one device-neutral brush preview in panel coordinates."""

    panel_x: float
    panel_y: float
    diameter: float
    erase: bool
    device: PointerDeviceKind
    contact: bool

    @classmethod
    def at(
        cls,
        position: QPointF,
        *,
        diameter: float,
        erase: bool,
        device: PointerDeviceKind,
        contact: bool,
    ) -> "BrushPreview":
        """Copy one preview observation into immutable scalar state."""
        return cls(
            panel_x=float(position.x()),
            panel_y=float(position.y()),
            diameter=max(0.01, float(diameter)),
            erase=bool(erase),
            device=device,
            contact=bool(contact),
        )

    @property
    def position(self) -> QPointF:
        """Return the preview center in logical panel coordinates."""
        return QPointF(self.panel_x, self.panel_y)

    def logical_bounds(
        self,
        *,
        zoom: float,
        dpr: float,
        padding: float = 4.0,
    ) -> QRect:
        """Return conservative logical repaint bounds for this preview."""
        logical_diameter = self.diameter * max(0.0, float(zoom)) / max(0.01, float(dpr))
        radius = logical_diameter / 2.0
        bounds = QRectF(
            self.panel_x - radius,
            self.panel_y - radius,
            logical_diameter,
            logical_diameter,
        ).toAlignedRect()
        margin = max(1, int(round(float(padding))))
        return bounds.adjusted(-margin, -margin, margin, margin)


class BrushPreviewRenderer:
    """Render direct-input feedback independently from the platform cursor."""

    def draw(
        self,
        painter: QPainter,
        preview: BrushPreview,
        *,
        zoom: float,
        dpr: float,
        color: QColor,
    ) -> None:
        """Draw a clipped high-contrast ring matching the effective brush size."""
        logical_diameter = (
            preview.diameter * max(0.0, float(zoom)) / max(0.01, float(dpr))
        )
        if logical_diameter <= 0.0:
            return
        center = preview.position
        radius = logical_diameter / 2.0
        ellipse = QRectF(
            center.x() - radius,
            center.y() - radius,
            logical_diameter,
            logical_diameter,
        )
        painter.save()
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            draw_brush_outline(painter, ellipse, color)
            if preview.erase:
                self._draw_erase_indicator(
                    painter,
                    center,
                    logical_diameter,
                )
        finally:
            painter.restore()

    @staticmethod
    def _draw_erase_indicator(
        painter: QPainter,
        center: QPointF,
        diameter: float,
    ) -> None:
        """Draw a compact high-contrast minus sign inside an eraser preview."""
        half_length = max(2.0, min(8.0, diameter * 0.16))
        y = center.y() + min(8.0, diameter * 0.2)
        start = QPointF(center.x() - half_length, y)
        end = QPointF(center.x() + half_length, y)
        outline = QPen(QColor(Qt.GlobalColor.black), 3.0)
        outline.setCosmetic(True)
        outline.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(outline)
        painter.drawLine(start, end)
        foreground = QPen(QColor(Qt.GlobalColor.white), 1.0)
        foreground.setCosmetic(True)
        foreground.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(foreground)
        painter.drawLine(start, end)
