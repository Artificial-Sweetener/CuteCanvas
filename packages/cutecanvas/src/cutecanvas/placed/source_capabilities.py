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
"""Focused scene-source capabilities for placed raster assets."""

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize
from PySide6.QtGui import QImage

from qpane.sdk.scene import (
    LayerSourceReference,
    RasterPresentation,
    RasterProductPolicy,
)

from ..resources import ProjectResourceReference
from .store import PlacedAssetStore


class PlacedAssetSourceCapabilities:
    """Adapt placed-asset authority to focused scene capabilities."""

    def __init__(self, assets: PlacedAssetStore) -> None:
        """Bind the authoritative placed-asset store."""
        self._assets = assets

    def presentation_for(
        self,
        source: LayerSourceReference,
    ) -> RasterPresentation | None:
        """Return ordinary image-raster presentation for placed pixels."""
        return (
            RasterPresentation.IMAGE
            if isinstance(source, ProjectResourceReference)
            else None
        )

    def product_policy(self, source: LayerSourceReference) -> RasterProductPolicy:
        """Return the stable shared-product policy for decoded asset pixels."""
        return RasterProductPolicy.CACHEABLE

    def source_size(self, source: LayerSourceReference) -> QSize | None:
        """Return authoritative decoded pixel dimensions."""
        snapshot = self._snapshot(source)
        return None if snapshot is None else QSize(snapshot.source_size)

    def source_path(self, source: LayerSourceReference) -> Path | None:
        """Return linked provenance when present."""
        snapshot = self._snapshot(source)
        return None if snapshot is None else snapshot.source_path

    def source_image(
        self,
        source: LayerSourceReference,
        *,
        scale: float | None = None,
    ) -> QImage | None:
        """Return detached last-valid placed pixels."""
        snapshot = self._snapshot(source)
        return (
            None
            if snapshot is None or snapshot.image is None
            else QImage(snapshot.image)
        )

    def contains(self, source: LayerSourceReference, point: QPointF) -> bool:
        """Hit test placed content by source alpha."""
        image = self.source_image(source)
        x = int(point.x())
        y = int(point.y())
        if image is None or x < 0 or y < 0 or x >= image.width() or y >= image.height():
            return False
        return image.pixelColor(x, y).alpha() > 0

    def content_bounds(self, source: LayerSourceReference) -> QRectF | None:
        """Return alpha-tight bounds cached by immutable content revision."""
        if not isinstance(source, ProjectResourceReference):
            return None
        return self._assets.content_bounds(source.resource_id)

    def storage_bounds(self, source: LayerSourceReference) -> QRectF | None:
        """Return decoded image storage bounds."""
        size = self.source_size(source)
        return None if size is None else QRectF(0.0, 0.0, size.width(), size.height())

    def authored_bounds(self, source: LayerSourceReference) -> QRectF | None:
        """Return the placed asset's intrinsic authored rectangle."""
        return self.storage_bounds(source)

    def _snapshot(self, source: LayerSourceReference):
        """Resolve one typed source through its owning store."""
        return (
            None
            if not isinstance(source, ProjectResourceReference)
            else self._assets.get(source.resource_id)
        )
