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
"""Raster capabilities for the rendering-owned placeholder source."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QImage

from ..scene.source_capabilities import RasterPresentation, RasterProductPolicy
from ..scene.source_references import LayerSourceReference, PlaceholderImageReference


class PlaceholderSourceCapabilities:
    """Adapt the current placeholder payload to focused source contracts."""

    def __init__(self) -> None:
        """Initialize without a placeholder payload provider."""
        self._provider: Callable[[], object | None] = lambda: None

    @property
    def presentation(self) -> RasterPresentation:
        """Return ordinary image-raster presentation."""
        return RasterPresentation.IMAGE

    def product_policy(self, source: LayerSourceReference) -> RasterProductPolicy:
        """Return the stable shared-product policy for placeholder pixels."""
        return RasterProductPolicy.CACHEABLE

    def set_provider(self, provider: Callable[[], object | None]) -> None:
        """Install the catalog-controller placeholder payload provider."""
        self._provider = provider

    def source_image(
        self,
        source: LayerSourceReference,
        *,
        scale: float | None = None,
    ) -> QImage | None:
        """Return the current placeholder image when identity matches."""
        payload = self._payload(source)
        image = None if payload is None else getattr(payload, "image", None)
        return None if image is None or image.isNull() else QImage(image)

    def source_size(self, source: LayerSourceReference) -> QSize | None:
        """Return current placeholder dimensions."""
        image = self.source_image(source)
        return None if image is None else image.size()

    def source_path(self, source: LayerSourceReference) -> Path | None:
        """Return the current placeholder path when present."""
        payload = self._payload(source)
        return None if payload is None else getattr(payload, "source_path", None)

    def contains(self, source: LayerSourceReference, point: QPointF) -> bool:
        """Treat placeholder bounds as occupied after geometry clipping."""
        return self._payload(source) is not None

    def _payload(self, source: LayerSourceReference) -> object | None:
        """Return the current payload only for its typed source reference."""
        return (
            self._provider() if isinstance(source, PlaceholderImageReference) else None
        )
