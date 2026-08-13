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
"""Mask source resolution for the generic scene rendering registry."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize
from PySide6.QtGui import QImage, QPixmap
from qpane.sdk.raster import present_hybrid_sample
from qpane.sdk.scene import (
    LayerSourceReference,
    RasterBounds,
    RasterPresentation,
    RasterProductPolicy,
    RasterSourcePatch,
)

from cutecanvas.coverage import CoverageSnapshot
from cutecanvas.coverage.boundary import sparse_coverage_convex_boundary
from cutecanvas.scene.pixel_fragments import RasterPixelFormat
from cutecanvas.scene.pixel_transitions import RasterPixelTransition
from cutecanvas.scene.source_capabilities import PixelSampleGeometry
from qpane import HybridPresentationStyle, HybridSource

from ..resources import ProjectResourceReference
from .hybrid_source import MaskHybridSourceFactory
from .live_preview_raster import LiveMaskPreviewPatches
from .mask import MaskLayer

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

    def uses_local_live_preview(self, mask_id: uuid.UUID) -> bool:
        """Return whether this view renders a decimated provisional product."""
        ...

    def live_preview_patches(
        self,
        mask_id: uuid.UUID,
    ) -> LiveMaskPreviewPatches | None:
        """Return native provisional patches for region-sampled presentation."""
        ...

    def render_revision(self, mask_id: uuid.UUID) -> int:
        """Return the current content and appearance render identity."""
        ...

    def effective_source_bounds(self, mask_id: uuid.UUID) -> RasterBounds | None:
        """Return durable bounds united with provisional visible coverage."""
        ...

    def hybrid_style(self, mask_id: uuid.UUID) -> HybridPresentationStyle:
        """Return immutable presentation values for hybrid sampling."""
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
    hybrids: MaskHybridSourceFactory = field(default_factory=MaskHybridSourceFactory)
    _boundary_cache: dict[
        uuid.UUID,
        tuple[object, tuple[QPointF, ...]],
    ] = field(default_factory=dict, compare=False, repr=False)

    def presentation_for(
        self,
        source: LayerSourceReference,
    ) -> RasterPresentation | None:
        """Return overlay-raster presentation for mask coverage."""
        return (
            RasterPresentation.OVERLAY
            if isinstance(source, ProjectResourceReference)
            else None
        )

    def product_policy(self, source: LayerSourceReference) -> RasterProductPolicy:
        """Keep durable mask products cacheable during transient native painting."""
        if not isinstance(source, ProjectResourceReference):
            return RasterProductPolicy.CACHEABLE
        return (
            RasterProductPolicy.VOLATILE
            if self.renders.uses_local_live_preview(source.resource_id)
            else RasterProductPolicy.CACHEABLE
        )

    def source_image(
        self,
        source: LayerSourceReference,
        *,
        scale: float | None = None,
    ) -> QImage | None:
        """Return durable pixels for dense rendering and transient fallback."""
        if not isinstance(source, ProjectResourceReference):
            return None
        pixmap = (
            self.renders.peek_by_id(source.resource_id)
            if scale is None
            else self.renders.get_best_by_id(source.resource_id, scale=scale)
        )
        if pixmap is not None and not pixmap.isNull():
            return pixmap.toImage()
        layer = self.assets.get_layer(source.resource_id)
        if (
            layer is not None
            and layer.coverage.raster.content_bounds() is None
            and not layer.coverage.has_retained_items
        ):
            transparent = QImage(1, 1, QImage.Format_ARGB32_Premultiplied)
            transparent.fill(0)
            return transparent
        return None

    def source_size(self, source: LayerSourceReference) -> QSize | None:
        """Return mask storage dimensions without copying authoritative pixels."""
        if not isinstance(source, ProjectResourceReference):
            return None
        layer = self.assets.get_layer(source.resource_id)
        bounds = (
            None if layer is None else self._effective_source_bounds(source.resource_id)
        )
        return None if bounds is None else QSize(bounds.width, bounds.height)

    def source_patches(
        self,
        source: LayerSourceReference,
        visible_bounds: RasterBounds,
    ) -> tuple[RasterSourcePatch, ...] | None:
        """Return stable sparse tiles while volatile previews use dense fallback."""
        if not isinstance(source, ProjectResourceReference):
            return ()
        if self.renders.live_preview_patches(source.resource_id) is not None:
            return None
        if self.renders.uses_local_live_preview(source.resource_id):
            return None
        layer = self.assets.get_layer(source.resource_id)
        logical_bounds = None if layer is None else layer.coverage.source_bounds()
        if layer is None or logical_bounds is None:
            return ()
        if layer.coverage.has_retained_items:
            return ()
        if layer.coverage.content_bounds() is None:
            return ()
        if (
            max(logical_bounds.width, logical_bounds.height)
            <= _MAX_DENSE_SAMPLE_DIMENSION
            and layer.coverage.raster.sparse_tile_count(visible_bounds)
            > _MAX_VISIBLE_PATCH_PRODUCTS
        ):
            return None
        patches: list[RasterSourcePatch] = []
        for tile in layer.coverage.raster.sparse_tiles(visible_bounds):
            bounds = tile.bounds.intersection(logical_bounds)
            if bounds is None:
                continue
            bleed = RasterBounds(
                bounds.x - 1,
                bounds.y - 1,
                bounds.width + 2,
                bounds.height + 2,
            )
            pixels = layer.coverage.raster.capture_region(bleed)
            patches.append(
                RasterSourcePatch(
                    bounds,
                    self.renders.present_patch(source.resource_id, bounds, pixels),
                    bleed,
                )
            )
        return tuple(patches)

    def hybrid_document(self, source: LayerSourceReference) -> HybridSource | None:
        """Return stable coverage through QPane's hybrid tile renderer."""
        if not isinstance(source, ProjectResourceReference):
            return None
        if self.renders.uses_local_live_preview(source.resource_id):
            return None
        return self.hybrid_document_with_style(
            source,
            self.renders.hybrid_style(source.resource_id),
        )

    def hybrid_document_with_style(
        self,
        source: ProjectResourceReference,
        style: HybridPresentationStyle,
    ) -> HybridSource | None:
        """Resolve durable or provisional coverage with one requested style."""
        layer = self.assets.get_layer(source.resource_id)
        if layer is None:
            return None
        revision = self.renders.render_revision(source.resource_id)
        effective_bounds = self._effective_source_bounds(source.resource_id)
        durable_bounds = layer.coverage.source_bounds()
        if effective_bounds is not None and effective_bounds != durable_bounds:
            return self.hybrids.source_with_provisional_bounds(
                layer,
                style,
                revision,
                effective_bounds,
            )
        return self.hybrids.source(layer, style, revision)

    def source_path(self, source: LayerSourceReference) -> Path | None:
        """Return no path because mask assets are memory-backed."""
        return None

    def content_bounds(self, source: LayerSourceReference) -> QRectF | None:
        """Return continuous visible bounds for one mask source."""
        if not isinstance(source, ProjectResourceReference):
            return None
        layer = self.assets.get_layer(source.resource_id)
        if layer is None:
            return None
        durable = layer.coverage.manipulation_bounds()
        preview = self.renders.live_preview_patches(source.resource_id)
        provisional = None if preview is None else preview.content_bounds
        if provisional is None:
            return durable
        provisional_rect = _rectf(provisional)
        return provisional_rect if durable is None else durable.united(provisional_rect)

    def content_boundary(
        self,
        source: LayerSourceReference,
    ) -> tuple[QPointF, ...]:
        """Return a revision-cached polygon around durable visible coverage."""
        if not isinstance(source, ProjectResourceReference):
            return ()
        layer = self.assets.get_layer(source.resource_id)
        if layer is None:
            return ()
        if layer.coverage.has_retained_items:
            return ()
        revision = layer.coverage.revision
        cached = self._boundary_cache.get(source.resource_id)
        if cached is not None and cached[0] == revision:
            return tuple(QPointF(point) for point in cached[1])
        boundary = sparse_coverage_convex_boundary(
            layer.coverage.raster.state_snapshot()
        )
        self._boundary_cache[source.resource_id] = (revision, boundary)
        return tuple(QPointF(point) for point in boundary)

    def storage_bounds(self, source: LayerSourceReference) -> QRectF | None:
        """Return sparse raster storage independently of retained mask geometry."""
        if not isinstance(source, ProjectResourceReference):
            return None
        layer = self.assets.get_layer(source.resource_id)
        bounds = None if layer is None else layer.coverage.raster.bounds
        return None if bounds is None else _rectf(bounds)

    def authored_bounds(self, source: LayerSourceReference) -> QRectF | None:
        """Return finite bounds encompassing raster and retained mask authorship."""
        if not isinstance(source, ProjectResourceReference):
            return None
        layer = self.assets.get_layer(source.resource_id)
        bounds = (
            None if layer is None else self._effective_source_bounds(source.resource_id)
        )
        return None if bounds is None else _rectf(bounds)

    def _effective_source_bounds(
        self,
        mask_id: uuid.UUID,
    ) -> RasterBounds | None:
        """Return durable geometry united with separately composed preview pixels."""
        return self.renders.effective_source_bounds(mask_id)

    def contains(self, source: LayerSourceReference, point: QPointF) -> bool:
        """Select mask layers only where their authoritative pixels are painted."""
        if not isinstance(source, ProjectResourceReference):
            return False
        layer = self.assets.get_layer(source.resource_id)
        if layer is None:
            return False
        x = int(point.x())
        y = int(point.y())
        return layer.coverage.coverage_value(x, y) > 0

    def coverage_snapshot(
        self,
        source: LayerSourceReference,
        bounds: RasterBounds | None = None,
    ) -> CoverageSnapshot | None:
        """Return authoritative mask coverage as a detached snapshot."""
        if not isinstance(source, ProjectResourceReference):
            return None
        layer = self.assets.get_layer(source.resource_id)
        if layer is None:
            return None
        snapshot = layer.coverage.snapshot(bounds)
        return None if snapshot.bounds is None else snapshot

    def present_pixels(
        self,
        source: LayerSourceReference,
        pixel_format: RasterPixelFormat,
        pixels: np.ndarray,
        target_size: QSize | None = None,
    ) -> QImage | None:
        """Colorize canonical mask pixels with their current layer appearance."""
        if (
            not isinstance(source, ProjectResourceReference)
            or pixel_format is not RasterPixelFormat.COVERAGE8
        ):
            return None
        return self.renders.present_pixels(source.resource_id, pixels, target_size)

    def present_transition_samples(
        self,
        source: LayerSourceReference,
        pixel_format: RasterPixelFormat,
        transition: RasterPixelTransition,
        samples: tuple[PixelSampleGeometry, ...],
    ) -> tuple[QImage, ...] | None:
        """Sample one virtual mask transition through the durable hybrid evaluator."""
        if (
            not isinstance(source, ProjectResourceReference)
            or pixel_format is not RasterPixelFormat.COVERAGE8
        ):
            return None
        return self.present_transition_samples_with_style(
            source,
            transition,
            samples,
            self.renders.hybrid_style(source.resource_id),
        )

    def present_transition_samples_with_style(
        self,
        source: ProjectResourceReference,
        transition: RasterPixelTransition,
        samples: tuple[PixelSampleGeometry, ...],
        style: HybridPresentationStyle,
    ) -> tuple[QImage, ...] | None:
        """Sample one virtual mask transition with an authoritative style."""
        layer = self.assets.get_layer(source.resource_id)
        if layer is None:
            return None
        hybrid = self.hybrids.source_with_transition(
            layer,
            style,
            self.renders.render_revision(source.resource_id),
            transition,
        )
        if hybrid is None:
            return None
        return tuple(
            present_hybrid_sample(
                hybrid.document,
                hybrid.style,
                sample.source_rect,
                sample.pixel_size,
            )
            for sample in samples
        )


def _rectf(bounds: RasterBounds) -> QRectF:
    """Return continuous geometry for one integer raster envelope."""
    return QRectF(bounds.x, bounds.y, bounds.width, bounds.height)
