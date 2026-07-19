#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Mask source resolution for the generic scene rendering registry."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QImage, QPixmap

from ..coverage import CoverageSnapshot
from ..scene.identity import SceneLayerAssetKey
from ..scene.pixel_fragments import RasterPixelFormat
from ..scene.sources import LayerSource, MaskLayerSource
from .mask import MaskLayer


class MaskAssetLookup(Protocol):
    """Resolve authoritative mask assets by identifier."""

    def get_layer(self, mask_id: uuid.UUID) -> MaskLayer | None:
        """Return one mask asset when present."""
        ...


class MaskRenderLookup(Protocol):
    """Resolve derived colorized mask rasters."""

    def get_by_id(
        self, mask_id: uuid.UUID, *, scale: float | None = None
    ) -> QPixmap | None:
        """Return a colorized mask pixmap at the requested scale."""
        ...

    def present_pixels(self, mask_id: uuid.UUID, pixels: np.ndarray) -> QImage:
        """Return canonical mask pixels with the mask's current presentation."""
        ...


@dataclass(frozen=True, slots=True)
class MaskLayerSourceResolver:
    """Resolve colorized mask rasters without rendering-service reach-through."""

    assets: MaskAssetLookup
    renders: MaskRenderLookup

    def supports_source(self, source: LayerSource) -> bool:
        """Return True for mask layer sources."""
        return isinstance(source, MaskLayerSource)

    def source_image(self, source: LayerSource) -> QImage | None:
        """Return authoritative grayscale pixels for source geometry."""
        if not isinstance(source, MaskLayerSource):
            return None
        layer = self.assets.get_layer(source.mask_id)
        if layer is None:
            return None
        image = layer.mask_image
        return None if image.isNull() else image

    def source_size(self, source: LayerSource) -> QSize | None:
        """Return mask storage dimensions without copying authoritative pixels."""
        if not isinstance(source, MaskLayerSource):
            return None
        layer = self.assets.get_layer(source.mask_id)
        bounds = None if layer is None else layer.surface.bounds
        return None if bounds is None else QSize(bounds.width, bounds.height)

    def source_path(self, source: LayerSource) -> Path | None:
        """Return no path because mask assets are memory-backed."""
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
        """Return the controller-cached mask raster nearest ``target_width``."""
        if not isinstance(source, MaskLayerSource) or source_size.width() <= 0:
            return None
        scale = max(1e-6, float(target_width) / source_size.width())
        pixmap = self.renders.get_by_id(source.mask_id, scale=scale)
        return None if pixmap is None or pixmap.isNull() else pixmap.toImage()

    def selection_contains(self, source: LayerSource, point: QPointF) -> bool:
        """Select mask layers only where their authoritative pixels are painted."""
        if not isinstance(source, MaskLayerSource):
            return False
        layer = self.assets.get_layer(source.mask_id)
        if layer is None:
            return False
        x = int(point.x())
        y = int(point.y())
        return layer.surface.storage_value(x, y) > 0

    def coverage_snapshot(self, source: LayerSource) -> CoverageSnapshot | None:
        """Return authoritative mask coverage as a detached snapshot."""
        if not isinstance(source, MaskLayerSource):
            return None
        layer = self.assets.get_layer(source.mask_id)
        return None if layer is None else layer.surface.snapshot()

    def present_pixels(
        self,
        source: LayerSource,
        pixel_format: RasterPixelFormat,
        pixels: np.ndarray,
    ) -> QImage | None:
        """Colorize canonical mask pixels with their current layer appearance."""
        if (
            not isinstance(source, MaskLayerSource)
            or pixel_format is not RasterPixelFormat.COVERAGE8
        ):
            return None
        return self.renders.present_pixels(source.mask_id, pixels)
