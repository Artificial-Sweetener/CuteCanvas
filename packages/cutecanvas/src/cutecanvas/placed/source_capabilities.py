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

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize
from PySide6.QtGui import QImage
from qpane.sdk.raster import qimage_to_numpy_argb32
from qpane.sdk.scene import (
    LayerSourceReference,
    RasterPresentation,
    RasterProductPolicy,
)

from .source_reference import PlacedAssetReference
from .store import PlacedAssetStore


class PlacedAssetSourceCapabilities:
    """Adapt placed-asset authority to focused scene capabilities."""

    def __init__(self, assets: PlacedAssetStore) -> None:
        """Bind the authoritative placed-asset store."""
        self._assets = assets
        self._content_bounds_cache: dict[tuple[object, int], QRectF | None] = {}

    @property
    def presentation(self) -> RasterPresentation:
        """Return ordinary image-raster presentation."""
        return RasterPresentation.IMAGE

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
        snapshot = self._snapshot(source)
        if snapshot is None or snapshot.image is None:
            return None
        key = (source.resource_id, snapshot.content_revision)
        if key in self._content_bounds_cache:
            cached = self._content_bounds_cache[key]
            return None if cached is None else QRectF(cached)
        alpha = qimage_to_numpy_argb32(snapshot.image)[:, :, 3]
        occupied = np.argwhere(alpha > 0)
        if occupied.size == 0:
            bounds = None
        else:
            top, left = occupied.min(axis=0)
            bottom, right = occupied.max(axis=0) + 1
            bounds = QRectF(
                float(left),
                float(top),
                float(right - left),
                float(bottom - top),
            )
        self._content_bounds_cache[key] = None if bounds is None else QRectF(bounds)
        return None if bounds is None else QRectF(bounds)

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
            if not isinstance(source, PlacedAssetReference)
            else self._assets.get(source.asset_id)
        )
