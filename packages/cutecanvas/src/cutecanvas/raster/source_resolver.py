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
"""Scene source resolution for editable color raster assets."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize
from PySide6.QtGui import QImage
from qpane.sdk.raster import (
    numpy_to_qimage_argb32,
)
from qpane.sdk.scene import (
    LayerSourceReference,
    RasterBounds,
    RasterPresentation,
    RasterProductPolicy,
    RasterSourcePatch,
)

from cutecanvas.scene.pixel_fragments import RasterPixelFormat
from cutecanvas.scene.pixel_transitions import RasterPixelTransition
from cutecanvas.scene.source_capabilities import PixelSampleGeometry

from ..resources import ProjectResourceReference
from .assets import EditableRasterAssetStore
from .presentation_state import EditableRasterPresentationState
from .preview_sampling import sample_argb32_preview

_MAX_VISIBLE_PATCH_PRODUCTS = 4
_MAX_DENSE_SAMPLE_BYTES = 128 * 1024 * 1024


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

    def presentation_for(
        self,
        source: LayerSourceReference,
    ) -> RasterPresentation | None:
        """Return ordinary image-raster presentation for editable pixels."""
        return (
            RasterPresentation.IMAGE
            if isinstance(source, ProjectResourceReference)
            else None
        )

    def product_policy(self, source: LayerSourceReference) -> RasterProductPolicy:
        """Return the stable shared-product policy for editable pixels."""
        return (
            RasterProductPolicy.VOLATILE
            if isinstance(source, ProjectResourceReference)
            and self._presentation_state.is_live(source.resource_id)
            else RasterProductPolicy.CACHEABLE
        )

    def source_image(
        self,
        source: LayerSourceReference,
        *,
        scale: float | None = None,
    ) -> QImage | None:
        """Return a bounded dense source or defer to sparse patch presentation."""
        asset = self._asset(source)
        if asset is None:
            return None
        bounds = asset.surface.bounds
        if bounds.width * bounds.height * 4 > _MAX_DENSE_SAMPLE_BYTES:
            return None
        if scale is not None:
            return asset.surface.sampled_qimage(scale)
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

    def content_bounds(self, source: LayerSourceReference) -> QRectF | None:
        """Return incremental alpha-tight bounds for editable raster content."""
        asset = self._asset(source)
        bounds = None if asset is None else asset.surface.content_bounds()
        return None if bounds is None else _rectf(bounds)

    def storage_bounds(self, source: LayerSourceReference) -> QRectF | None:
        """Return allocated editable raster storage."""
        asset = self._asset(source)
        return None if asset is None else _rectf(asset.surface.bounds)

    def authored_bounds(self, source: LayerSourceReference) -> QRectF | None:
        """Return the editable raster's explicit authored envelope."""
        return self.storage_bounds(source)

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
        dense_bytes = surface_bounds.width * surface_bounds.height * 4
        if (
            dense_bytes <= _MAX_DENSE_SAMPLE_BYTES
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
            not isinstance(source, ProjectResourceReference)
            or pixel_format is not RasterPixelFormat.PREMULTIPLIED_ARGB32
        ):
            return None
        return (
            numpy_to_qimage_argb32(pixels)
            if target_size is None
            else sample_argb32_preview(pixels, target_size)
        )

    def present_transition_samples(
        self,
        source: LayerSourceReference,
        pixel_format: RasterPixelFormat,
        transition: RasterPixelTransition,
        samples: tuple[PixelSampleGeometry, ...],
    ) -> tuple[QImage, ...] | None:
        """Defer exact virtual sampling until editable rasters require it."""
        del source, pixel_format, transition, samples
        return None

    def _asset(self, source: LayerSourceReference):
        """Resolve an editable asset from a typed layer source."""
        return (
            None
            if not isinstance(source, ProjectResourceReference)
            else self._assets.get(source.resource_id)
        )


def _rectf(bounds: RasterBounds) -> QRectF:
    """Return continuous geometry for one integer raster envelope."""
    return QRectF(bounds.x, bounds.y, bounds.width, bounds.height)
