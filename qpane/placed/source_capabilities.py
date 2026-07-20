#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Focused scene-source capabilities for placed raster assets."""

from pathlib import Path

from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QImage

from ..scene.source_capabilities import RasterPresentation, RasterProductPolicy
from ..scene.source_references import LayerSourceReference
from .source_reference import PlacedAssetReference
from .store import PlacedAssetStore


class PlacedAssetSourceCapabilities:
    """Adapt placed-asset authority to focused scene capabilities."""

    def __init__(self, assets: PlacedAssetStore) -> None:
        """Bind the authoritative placed-asset store."""
        self._assets = assets

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

    def _snapshot(self, source: LayerSourceReference):
        """Resolve one typed source through its owning store."""
        return (
            None
            if not isinstance(source, PlacedAssetReference)
            else self._assets.get(source.asset_id)
        )
