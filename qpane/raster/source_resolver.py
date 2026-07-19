#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Scene source resolution for editable color raster assets."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QImage

from ..coverage import CoverageSnapshot
from ..scene.identity import SceneLayerAssetKey
from ..scene.pixel_fragments import RasterPixelFormat
from ..scene.sources import EditableRasterSource, LayerSource
from .assets import EditableRasterAssetStore
from .image_conversion import numpy_to_qimage_argb32


class EditableRasterSourceResolver:
    """Resolve full-resolution pixels from editable raster assets."""

    def __init__(self, assets: EditableRasterAssetStore) -> None:
        """Bind the authoritative asset store."""
        self._assets = assets

    def supports_source(self, source: LayerSource) -> bool:
        """Return whether ``source`` references an editable color raster."""
        return isinstance(source, EditableRasterSource)

    def source_image(self, source: LayerSource) -> QImage | None:
        """Return detached full-resolution color pixels."""
        asset = self._asset(source)
        return None if asset is None else asset.surface.snapshot_qimage()

    def source_size(self, source: LayerSource) -> QSize | None:
        """Return authoritative storage dimensions."""
        asset = self._asset(source)
        if asset is None:
            return None
        bounds = asset.surface.bounds
        return QSize(bounds.width, bounds.height)

    def source_path(self, source: LayerSource) -> Path | None:
        """Return no path because editable assets are composition memory."""
        return None

    def best_fit_image(
        self,
        source: LayerSource,
        *,
        asset_key: SceneLayerAssetKey,
        pyramid_asset_key: SceneLayerAssetKey,
        source_size: QSize,
        target_width: float,
    ) -> QImage | None:
        """Return authoritative pixels for normal render planning."""
        return self.source_image(source)

    def selection_contains(self, source: LayerSource, point: QPointF) -> bool:
        """Hit test editable rasters by source alpha."""
        image = self.source_image(source)
        x = int(point.x())
        y = int(point.y())
        if image is None or x < 0 or y < 0 or x >= image.width() or y >= image.height():
            return False
        return image.pixelColor(x, y).alpha() > 0

    def coverage_snapshot(self, source: LayerSource) -> CoverageSnapshot | None:
        """Return no selection coverage because this is a color source."""
        return None

    def present_pixels(
        self,
        source: LayerSource,
        pixel_format: RasterPixelFormat,
        pixels: np.ndarray,
    ) -> QImage | None:
        """Adapt canonical premultiplied pixels into a detached Qt image."""
        if (
            not isinstance(source, EditableRasterSource)
            or pixel_format is not RasterPixelFormat.PREMULTIPLIED_ARGB32
        ):
            return None
        return numpy_to_qimage_argb32(pixels)

    def _asset(self, source: LayerSource):
        """Resolve an editable asset from a typed layer source."""
        return (
            None
            if not isinstance(source, EditableRasterSource)
            else self._assets.get(source.raster_id)
        )
