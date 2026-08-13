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

"""Source-neutral brush preview value state and canvas rendering."""

from __future__ import annotations

from dataclasses import dataclass

from cutecanvas.ui.brush_feedback import (
    draw_brush_outline,
    draw_brush_path_outline,
)
from cutecanvas.ui.erase_indicator import EraseIndicatorRenderer
from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QTransform

from qpane import PointerDeviceKind


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
    ) -> BrushPreview:
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
        margin = max(1, round(float(padding)))
        return bounds.adjusted(-margin, -margin, margin, margin)


class BrushPreviewRenderer:
    """Render direct-input feedback independently from the platform cursor."""

    def __init__(
        self,
        erase_indicator: EraseIndicatorRenderer | None = None,
    ) -> None:
        """Capture the shared erase decoration collaborator."""
        self._erase_indicator = erase_indicator or EraseIndicatorRenderer()

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
                self._erase_indicator.draw(
                    painter,
                    ellipse,
                )
        finally:
            painter.restore()


@dataclass(frozen=True, slots=True)
class AffineBrushPreview:
    """Describe one affine brush footprint in logical panel coordinates."""

    center_x: float
    center_y: float
    axis_x_x: float
    axis_x_y: float
    axis_y_x: float
    axis_y_y: float
    contact: bool = False

    @property
    def center(self) -> QPointF:
        """Return the detached footprint center."""
        return QPointF(self.center_x, self.center_y)

    @property
    def axis_x(self) -> QPointF:
        """Return the detached horizontal radius vector."""
        return QPointF(self.axis_x_x, self.axis_x_y)

    def path(self) -> QPainterPath:
        """Return the affine projection of one unit-circle footprint."""
        unit = QPainterPath()
        unit.addEllipse(QRectF(-1.0, -1.0, 2.0, 2.0))
        return QTransform(
            self.axis_x_x,
            self.axis_x_y,
            self.axis_y_x,
            self.axis_y_y,
            self.center_x,
            self.center_y,
        ).map(unit)

    def logical_bounds(self, *, padding: float = 4.0) -> QRect:
        """Return conservative repaint bounds for the transformed footprint."""
        bounds = self.path().boundingRect().toAlignedRect()
        margin = max(1, round(float(padding)))
        return bounds.adjusted(-margin, -margin, margin, margin)


class AffineBrushPreviewRenderer:
    """Render one transformed sampled-area footprint and orientation cue."""

    def draw(
        self,
        painter: QPainter,
        preview: AffineBrushPreview,
        *,
        color: QColor,
    ) -> None:
        """Draw the exact affine footprint plus its transformed horizontal axis."""
        painter.save()
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            draw_brush_path_outline(painter, preview.path(), color)
            self._draw_orientation(painter, preview)
        finally:
            painter.restore()

    @staticmethod
    def _draw_orientation(
        painter: QPainter,
        preview: AffineBrushPreview,
    ) -> None:
        """Draw a compact axis cue that remains legible on circular tips."""
        center = preview.center
        axis = preview.axis_x
        length = max(3.0, min(12.0, (axis.x() ** 2 + axis.y() ** 2) ** 0.5))
        magnitude = max(1e-9, (axis.x() ** 2 + axis.y() ** 2) ** 0.5)
        endpoint = QPointF(
            center.x() + axis.x() * length / magnitude,
            center.y() + axis.y() * length / magnitude,
        )
        for color, width in (
            (QColor(Qt.GlobalColor.black), 3.0),
            (QColor(Qt.GlobalColor.white), 1.0),
        ):
            pen = QPen(color, width)
            pen.setCosmetic(True)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(center, endpoint)
