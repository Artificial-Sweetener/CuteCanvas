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
"""Resolve and publish the viewer's current base raster payload."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtGui import QImage, QMouseEvent, QPixmap

from ..rendering.sdk import RasterSource, RenderScene
from ..ui import copyToClipboard, drag_out_image

if TYPE_CHECKING:
    from ..viewer import QPane


class ViewerContent:
    """Own base-raster access, clipboard copy, and OS drag-out behavior."""

    def __init__(self, scene: Callable[[], RenderScene | None]) -> None:
        """Capture the active-scene provider without duplicating scene state."""
        self._scene = scene

    def image(self) -> QImage | None:
        """Return the current base raster through an implicitly shared handle."""
        source = self._source()
        if source is None:
            return None
        image = source.provider.image(None)
        if image is None or image.isNull():
            return None
        return QImage(image)

    def path(self) -> Path | None:
        """Return the current base raster's source path when one exists."""
        source = self._source()
        return None if source is None else source.path

    def copy_to_clipboard(self) -> bool:
        """Copy the current base raster to the system clipboard."""
        image = self.image()
        return False if image is None else copyToClipboard(QPixmap.fromImage(image))

    def start_drag(self, pane: QPane, event: QMouseEvent | None) -> None:
        """Start the configured OS drag for the current path-backed raster."""
        image = self.image()
        if image is None:
            return
        drag_out_image(pane, event, image=image, path=self.path())

    def _source(self) -> RasterSource | None:
        """Return the first visible base raster in scene stacking order."""
        scene = self._scene()
        if scene is None:
            return None
        for layer in scene.layers:
            if layer.visible and isinstance(layer.source, RasterSource):
                return layer.source
        return None
