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

from ..scene.pixel_fragments import RasterPixelFormat
from ..scene.raster import RasterBounds
from ..scene.source_capabilities import (
    RasterPresentation,
    RasterProductPolicy,
    RasterSourcePatch,
)
from ..scene.source_references import LayerSourceReference
from .assets import EditableRasterAssetStore
from .image_conversion import numpy_to_qimage_argb32, numpy_to_qimage_argb32_at_size
from .presentation_state import EditableRasterPresentationState
from .source_reference import EditableRasterReference

_MAX_VISIBLE_PATCH_PRODUCTS = 4
_MAX_DENSE_SAMPLE_DIMENSION = 32_768


class EditableRasterSourceCapabilities:
    """Adapt editable-raster authority to focused source capabilities."""

    def __init__(
        self,
        assets: EditableRasterAssetStore,
        presentation_state: EditableRasterPresentationState,
    ) -> None:
        """Bind the authoritative asset store."""
        self._assets = assets
        self._presentation_state = presentation_state

    @property
    def presentation(self) -> RasterPresentation:
        """Return ordinary image-raster presentation."""
        return RasterPresentation.IMAGE

    def product_policy(self, source: LayerSourceReference) -> RasterProductPolicy:
        """Return the stable shared-product policy for editable pixels."""
        return (
            RasterProductPolicy.VOLATILE
            if isinstance(source, EditableRasterReference)
            and self._presentation_state.is_live(source.raster_id)
            else RasterProductPolicy.CACHEABLE
        )

    def source_image(
        self,
        source: LayerSourceReference,
        *,
        scale: float | None = None,
    ) -> QImage | None:
        """Return a dense small source or a sparse display sample."""
        asset = self._asset(source)
        if asset is None:
            return None
        if scale is not None:
            return asset.surface.sampled_qimage(scale)
        bounds = asset.surface.bounds
        if asset.surface.sparse_tile_count(bounds) > _MAX_VISIBLE_PATCH_PRODUCTS:
            return None
        return asset.surface.presentation_qimage()

    def source_size(self, source: LayerSourceReference) -> QSize | None:
        """Return authoritative storage dimensions."""
        asset = self._asset(source)
        if asset is None:
            return None
        bounds = asset.surface.bounds
        return QSize(bounds.width, bounds.height)

    def source_path(self, source: LayerSourceReference) -> Path | None:
        """Return no path because editable assets are composition memory."""
        return None

    def source_patches(
        self,
        source: LayerSourceReference,
        visible_bounds: RasterBounds,
    ) -> tuple[RasterSourcePatch, ...] | None:
        """Return sparse editable products without transparent-gap allocation."""
        asset = self._asset(source)
        if asset is None:
            return ()
        surface_bounds = asset.surface.bounds
        if (
            max(surface_bounds.width, surface_bounds.height)
            <= _MAX_DENSE_SAMPLE_DIMENSION
            and asset.surface.sparse_tile_count(visible_bounds)
            > _MAX_VISIBLE_PATCH_PRODUCTS
        ):
            return None
        return tuple(
            RasterSourcePatch(bounds, image, sample_bounds)
            for bounds, sample_bounds, image in asset.surface.presentation_tiles(
                visible_bounds
            )
        )

    def contains(self, source: LayerSourceReference, point: QPointF) -> bool:
        """Hit test editable rasters by source alpha."""
        asset = self._asset(source)
        if asset is None:
            return False
        x = int(point.x())
        y = int(point.y())
        sample = RasterBounds(x, y, 1, 1)
        if not asset.surface.bounds.contains(sample):
            return False
        occupancy = asset.surface.capture_alpha_occupancy(sample)
        return bool(occupancy is not None and occupancy[0, 0] != 0)

    def present_pixels(
        self,
        source: LayerSourceReference,
        pixel_format: RasterPixelFormat,
        pixels: np.ndarray,
        target_size: QSize | None = None,
    ) -> QImage | None:
        """Adapt canonical premultiplied pixels into a detached Qt image."""
        if (
            not isinstance(source, EditableRasterReference)
            or pixel_format is not RasterPixelFormat.PREMULTIPLIED_ARGB32
        ):
            return None
        return (
            numpy_to_qimage_argb32(pixels)
            if target_size is None
            else numpy_to_qimage_argb32_at_size(pixels, target_size)
        )

    def _asset(self, source: LayerSourceReference):
        """Resolve an editable asset from a typed layer source."""
        return (
            None
            if not isinstance(source, EditableRasterReference)
            else self._assets.get(source.raster_id)
        )
