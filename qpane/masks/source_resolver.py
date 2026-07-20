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
from ..scene.pixel_fragments import RasterPixelFormat
from ..scene.raster import RasterBounds
from ..scene.source_capabilities import (
    RasterPresentation,
    RasterProductPolicy,
    RasterSourcePatch,
)
from ..scene.source_references import LayerSourceReference
from .mask import MaskLayer
from .source_reference import MaskAssetReference

_MAX_VISIBLE_PATCH_PRODUCTS = 4
_MAX_DENSE_SAMPLE_DIMENSION = 32_768


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

    def peek_by_id(
        self, mask_id: uuid.UUID, *, scale: float | None = None
    ) -> QPixmap | None:
        """Return an already-derived mask product without starting heavy work."""
        ...

    def get_best_by_id(self, mask_id: uuid.UUID, *, scale: float) -> QPixmap | None:
        """Return a density-suitable cached product or derive one sampled product."""
        ...

    def is_live_preview(self, mask_id: uuid.UUID) -> bool:
        """Return whether a volatile preview currently changes this mask product."""
        ...

    def present_patch(
        self,
        mask_id: uuid.UUID,
        bounds: RasterBounds,
        pixels_with_bleed: np.ndarray,
    ) -> QImage:
        """Return one cached colorized source-local tile."""
        ...

    def present_pixels(
        self,
        mask_id: uuid.UUID,
        pixels: np.ndarray,
        target_size: QSize | None = None,
    ) -> QImage:
        """Return canonical mask pixels with the mask's current presentation."""
        ...


@dataclass(frozen=True, slots=True)
class MaskSourceCapabilities:
    """Adapt mask authority to its focused source capabilities."""

    assets: MaskAssetLookup
    renders: MaskRenderLookup

    @property
    def presentation(self) -> RasterPresentation:
        """Return overlay-raster presentation."""
        return RasterPresentation.OVERLAY

    def product_policy(self, source: LayerSourceReference) -> RasterProductPolicy:
        """Bypass shared products only while this mask's preview is changing."""
        if not isinstance(source, MaskAssetReference):
            return RasterProductPolicy.CACHEABLE
        return (
            RasterProductPolicy.VOLATILE
            if self.renders.is_live_preview(source.mask_id)
            else RasterProductPolicy.CACHEABLE
        )

    def source_image(
        self,
        source: LayerSourceReference,
        *,
        scale: float | None = None,
    ) -> QImage | None:
        """Return the full or explicitly sampled colorized presentation product."""
        if not isinstance(source, MaskAssetReference):
            return None
        pixmap = (
            self.renders.peek_by_id(source.mask_id)
            if scale is None
            else self.renders.get_best_by_id(source.mask_id, scale=scale)
        )
        return None if pixmap is None or pixmap.isNull() else pixmap.toImage()

    def source_size(self, source: LayerSourceReference) -> QSize | None:
        """Return mask storage dimensions without copying authoritative pixels."""
        if not isinstance(source, MaskAssetReference):
            return None
        layer = self.assets.get_layer(source.mask_id)
        bounds = None if layer is None else layer.surface.bounds
        return None if bounds is None else QSize(bounds.width, bounds.height)

    def source_patches(
        self,
        source: LayerSourceReference,
        visible_bounds: RasterBounds,
    ) -> tuple[RasterSourcePatch, ...] | None:
        """Return stable sparse tiles while volatile previews use dense fallback."""
        if not isinstance(source, MaskAssetReference):
            return ()
        if self.renders.is_live_preview(source.mask_id):
            return None
        layer = self.assets.get_layer(source.mask_id)
        logical_bounds = None if layer is None else layer.surface.bounds
        if layer is None or logical_bounds is None:
            return ()
        if (
            max(logical_bounds.width, logical_bounds.height)
            <= _MAX_DENSE_SAMPLE_DIMENSION
            and layer.surface.sparse_tile_count(visible_bounds)
            > _MAX_VISIBLE_PATCH_PRODUCTS
        ):
            return None
        patches: list[RasterSourcePatch] = []
        for tile in layer.surface.sparse_tiles(visible_bounds):
            bounds = tile.bounds.intersection(logical_bounds)
            if bounds is None:
                continue
            bleed = RasterBounds(
                bounds.x - 1,
                bounds.y - 1,
                bounds.width + 2,
                bounds.height + 2,
            )
            pixels = layer.surface.capture_region(bleed)
            patches.append(
                RasterSourcePatch(
                    bounds,
                    self.renders.present_patch(source.mask_id, bounds, pixels),
                    bleed,
                )
            )
        return tuple(patches)

    def source_path(self, source: LayerSourceReference) -> Path | None:
        """Return no path because mask assets are memory-backed."""
        return None

    def contains(self, source: LayerSourceReference, point: QPointF) -> bool:
        """Select mask layers only where their authoritative pixels are painted."""
        if not isinstance(source, MaskAssetReference):
            return False
        layer = self.assets.get_layer(source.mask_id)
        if layer is None:
            return False
        x = int(point.x())
        y = int(point.y())
        bounds = layer.surface.bounds
        if bounds is None:
            return False
        return layer.surface.storage_value(x - bounds.x, y - bounds.y) > 0

    def coverage_snapshot(
        self,
        source: LayerSourceReference,
        bounds: RasterBounds | None = None,
    ) -> CoverageSnapshot | None:
        """Return authoritative mask coverage as a detached snapshot."""
        if not isinstance(source, MaskAssetReference):
            return None
        layer = self.assets.get_layer(source.mask_id)
        if layer is None:
            return None
        surface_bounds = layer.surface.bounds
        if bounds is None:
            return layer.surface.snapshot()
        overlap = (
            None if surface_bounds is None else surface_bounds.intersection(bounds)
        )
        if overlap is None:
            return None
        return CoverageSnapshot(
            overlap,
            layer.surface.extent_policy,
            layer.surface.capture_region(overlap),
        )

    def present_pixels(
        self,
        source: LayerSourceReference,
        pixel_format: RasterPixelFormat,
        pixels: np.ndarray,
        target_size: QSize | None = None,
    ) -> QImage | None:
        """Colorize canonical mask pixels with their current layer appearance."""
        if (
            not isinstance(source, MaskAssetReference)
            or pixel_format is not RasterPixelFormat.COVERAGE8
        ):
            return None
        return self.renders.present_pixels(source.mask_id, pixels, target_size)
