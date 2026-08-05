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
"""Viewport geometry and navigation methods for the CuteCanvas facade."""

from __future__ import annotations

from math import isfinite

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize
from qpane.sdk.rendering import PanelHitTest

from cutecanvas.scene.geometry import aspect_scene_rect


class ViewApiMixin:
    """Expose viewport queries and navigation without owning view state."""

    @staticmethod
    def fitSceneRect(source_size: QSize, target_rect: QRectF) -> QRectF:
        """Return the largest centered aspect-preserving rectangle."""
        return aspect_scene_rect(source_size, target_rect, cover=False)

    @staticmethod
    def fillSceneRect(source_size: QSize, target_rect: QRectF) -> QRectF:
        """Return the smallest centered aspect-preserving covering rectangle."""
        return aspect_scene_rect(source_size, target_rect, cover=True)

    def currentZoom(self) -> float:
        """Return the current viewport zoom factor."""
        return float(self.view().viewport.zoom)

    def currentViewportRect(self) -> QRectF:
        """Return the latest physical viewport rectangle."""
        rect = self._last_viewport_rect
        return QRectF(rect) if rect is not None else self.physicalViewportRect()

    def sceneToPanelRect(self, scene_rect: QRectF) -> QRectF | None:
        """Map one absolute scene rectangle into logical widget coordinates.

        Args:
            scene_rect: Finite geometry in the active scene coordinate system.

        Returns:
            A detached widget-coordinate rectangle, or ``None`` when no active
            scene can provide a mapping.

        Raises:
            TypeError: If ``scene_rect`` is not a ``QRectF``.
            ValueError: If ``scene_rect`` is empty or contains non-finite values.
        """
        if not isinstance(scene_rect, QRectF):
            raise TypeError("scene_rect must be a QRectF")
        if not scene_rect.isValid() or not all(
            isfinite(value)
            for value in (
                scene_rect.x(),
                scene_rect.y(),
                scene_rect.width(),
                scene_rect.height(),
            )
        ):
            raise ValueError("scene_rect must be a valid QRectF")
        transform = self.view().scene_to_panel_transform()
        return None if transform is None else transform.mapRect(QRectF(scene_rect))

    def setPanZoomLocked(self, locked: bool) -> None:
        """Replace direct pan and zoom interaction permission."""

        self.view().viewport.set_locked(bool(locked))

    def setZoomFit(self) -> None:
        """Fit the active document to the viewport and recenter pan."""
        self.view().viewport.setZoomFit()

    def setZoom1To1(self, anchor: QPoint | QPointF | None = None) -> None:
        """Show native pixels while preserving an optional widget-space anchor."""
        self.view().viewport.setZoom1To1(anchor=anchor)

    def applyZoom(
        self,
        requested_zoom: float,
        anchor: QPoint | QPointF | None = None,
    ) -> None:
        """Apply one bounded zoom request around an optional widget-space anchor."""
        new_zoom = self._normalize_zoom_request(requested_zoom)
        if new_zoom is not None:
            self.view().viewport.applyZoom(new_zoom, anchor=anchor)

    def panelHitTest(self, panel_pos: QPoint) -> PanelHitTest | None:
        """Return render hit metadata at one panel position."""
        return self.view().panel_hit_test(panel_pos)
