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
"""Observe mounted viewport geometry through real Qt resize delivery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from PySide6.QtCore import QPointF, QRectF, QSize, QSizeF
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QApplication

from qpane.sdk.rendering import ViewportZoomMode


class ResizeProbeView(Protocol):
    """Describe the public QPane view geometry consumed by the probe."""

    def physical_viewport_rect(self) -> QRectF:
        """Return the current physical viewport rectangle."""
        ...

    def panel_to_scene_point(self, panel_pos: QPointF) -> QPointF | None:
        """Map one logical panel point into scene coordinates."""
        ...

    def scene_to_panel_transform(self) -> QTransform | None:
        """Return the current scene-to-panel transform."""
        ...


class ResizeProbeViewport(Protocol):
    """Describe viewport state required for resize observations."""

    zoom: float
    pan: QPointF

    def get_zoom_mode(self) -> ViewportZoomMode:
        """Return the active zoom mode."""
        ...


class ResizeProbeSurface(Protocol):
    """Describe a mounted QPane-compatible surface."""

    def resize(self, size: QSize) -> None:
        """Resize the surface."""
        ...

    def size(self) -> QSize:
        """Return the surface's logical size."""
        ...


@dataclass(frozen=True, slots=True)
class ViewportResizeObservation:
    """Record semantic state and logical presentation scale after one resize."""

    label: str
    logical_size: QSize
    physical_size: QSizeF
    zoom_mode: str
    zoom: float
    pan: QPointF
    scene_center: QPointF
    scene_basis_scale: QPointF


class MountedViewportResizeProbe:
    """Drive and observe a production viewport without opening a desktop window."""

    def __init__(
        self,
        qapp: QApplication,
        surface: ResizeProbeSurface,
        view: ResizeProbeView,
        viewport: ResizeProbeViewport,
    ) -> None:
        """Bind an already shown offscreen surface."""
        self._qapp = qapp
        self._surface = surface
        self._view = view
        self._viewport = viewport

    def resize_and_capture(
        self,
        label: str,
        size: QSize,
    ) -> ViewportResizeObservation:
        """Deliver one real resize and capture its resulting transform."""
        self._surface.resize(size)
        self._qapp.processEvents()
        return self.capture(label)

    def capture(self, label: str) -> ViewportResizeObservation:
        """Capture stored state plus the transform used to present scene pixels."""
        view = self._view
        physical_rect = view.physical_viewport_rect()
        physical_size = QSizeF(physical_rect.size())
        logical_size = QSize(self._surface.size())
        panel_center = QPointF(
            logical_size.width() / 2.0,
            logical_size.height() / 2.0,
        )
        scene_center = view.panel_to_scene_point(panel_center)
        transform = view.scene_to_panel_transform()
        if scene_center is None or transform is None:
            raise RuntimeError("mounted viewport has no active scene projection")
        origin = transform.map(QPointF(0.0, 0.0))
        x_basis = transform.map(QPointF(1.0, 0.0))
        y_basis = transform.map(QPointF(0.0, 1.0))
        viewport = self._viewport
        return ViewportResizeObservation(
            label=label,
            logical_size=logical_size,
            physical_size=physical_size,
            zoom_mode=str(viewport.get_zoom_mode().value),
            zoom=float(viewport.zoom),
            pan=QPointF(viewport.pan),
            scene_center=QPointF(scene_center),
            scene_basis_scale=QPointF(
                x_basis.x() - origin.x(),
                y_basis.y() - origin.y(),
            ),
        )
