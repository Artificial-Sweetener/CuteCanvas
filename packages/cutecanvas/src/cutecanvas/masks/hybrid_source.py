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
"""Project editable mask coverage into QPane's immutable hybrid source."""

from __future__ import annotations

import uuid
from collections import OrderedDict
from dataclasses import dataclass

from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QImage

from cutecanvas.coverage import CoverageDocumentEvaluator
from cutecanvas.coverage.document import CoverageItem, VectorCoverageItem
from cutecanvas.coverage.raster_sampling import (
    CoverageSurfaceSampler,
    coverage_image,
    project_coverage_image,
)
from cutecanvas.coverage.surface import CoverageSurface
from cutecanvas.scene.pixel_transitions import RasterPixelTransition
from qpane import (
    HybridCombineMode,
    HybridDocument,
    HybridPresentationStyle,
    HybridRasterPrimitive,
    HybridSource,
    HybridVectorPrimitive,
    RasterBounds,
)

from .mask import MaskLayer

_PRIMITIVE_CACHE_LIMIT = 4096
_HybridPrimitive = HybridRasterPrimitive | HybridVectorPrimitive


class MaskHybridSourceFactory:
    """Build lightweight render snapshots from authoritative mask coverage."""

    def __init__(self) -> None:
        """Create one reusable bounds evaluator for retained items."""
        self._evaluator = CoverageDocumentEvaluator()
        self._primitive_cache: OrderedDict[
            uuid.UUID,
            tuple[CoverageItem, _HybridPrimitive | None],
        ] = OrderedDict()

    def source(
        self,
        layer: MaskLayer,
        style: HybridPresentationStyle,
        presentation_revision: int,
        *,
        include_empty_raster: bool = False,
    ) -> HybridSource | None:
        """Return one immutable QPane source without evaluating visible pixels."""
        return self._source(
            layer,
            style,
            presentation_revision,
            CoverageSurfaceSampler(layer.coverage.raster),
            include_empty_raster=include_empty_raster,
        )

    def source_with_transition(
        self,
        layer: MaskLayer,
        style: HybridPresentationStyle,
        presentation_revision: int,
        transition: RasterPixelTransition,
    ) -> HybridSource | None:
        """Return a virtual hybrid source with one uncommitted raster transition."""
        return self._source(
            layer,
            style,
            presentation_revision,
            _TransitionSurfaceSampler(layer.coverage.raster, transition),
        )

    def _source(
        self,
        layer: MaskLayer,
        style: HybridPresentationStyle,
        presentation_revision: int,
        raster_sampler: CoverageSurfaceSampler | _TransitionSurfaceSampler,
        *,
        include_empty_raster: bool = False,
    ) -> HybridSource | None:
        """Build one hybrid snapshot around the supplied raster sampler."""
        bounds = layer.coverage.source_bounds()
        if bounds is None:
            return None
        primitives: list[_HybridPrimitive] = []
        raster_bounds = layer.coverage.raster.content_bounds()
        if isinstance(raster_sampler, _TransitionSurfaceSampler):
            raster_bounds = (
                raster_sampler.transition.patch_bounds
                if raster_bounds is None
                else raster_bounds.united(raster_sampler.transition.patch_bounds)
            )
        if raster_bounds is not None:
            primitives.append(
                HybridRasterPrimitive(
                    uuid.uuid5(layer.mask_id, "authoritative-raster"),
                    raster_bounds,
                    raster_sampler,
                )
            )
        elif include_empty_raster and not layer.coverage.has_retained_items:
            primitives.append(
                HybridRasterPrimitive(
                    uuid.uuid5(layer.mask_id, "empty-raster-substrate"),
                    RasterBounds(
                        bounds.x + bounds.width + 1,
                        bounds.y + bounds.height + 1,
                        1,
                        1,
                    ),
                    raster_sampler,
                )
            )
        for item in layer.coverage.retained.items:
            primitive = self._retained_primitive(item)
            if primitive is not None:
                primitives.append(primitive)
        raster_revision, retained_revision = layer.coverage.revision
        document_revision = _pair_revisions(raster_revision, retained_revision)
        return HybridSource(
            HybridDocument(
                layer.mask_id,
                bounds,
                tuple(primitives),
                document_revision,
            ),
            style,
            presentation_revision,
        )

    def _retained_primitive(self, item: CoverageItem) -> _HybridPrimitive | None:
        """Return one bounded cached projection of immutable retained authorship."""
        cached = self._primitive_cache.get(item.item_id)
        if cached is not None and cached[0] == item:
            self._primitive_cache.move_to_end(item.item_id)
            return cached[1]
        item_bounds = self._evaluator.item_bounds(item)
        primitive: _HybridPrimitive | None
        if item_bounds is None:
            primitive = None
        elif isinstance(item, VectorCoverageItem):
            primitive = HybridVectorPrimitive(
                item.item_id,
                item.geometry,
                item_bounds,
                HybridCombineMode(item.combine_mode.value),
                item.transform,
                item.feather_radius,
            )
        else:
            primitive = HybridRasterPrimitive(
                item.item_id,
                item_bounds,
                _RetainedItemSampler(item),
                HybridCombineMode(item.combine_mode.value),
            )
        self._primitive_cache[item.item_id] = (item, primitive)
        self._primitive_cache.move_to_end(item.item_id)
        if len(self._primitive_cache) > _PRIMITIVE_CACHE_LIMIT:
            self._primitive_cache.popitem(last=False)
        return primitive


@dataclass(frozen=True, slots=True)
class _TransitionSurfaceSampler:
    """Sample a virtual raster transition without mutating canonical storage."""

    surface: CoverageSurface
    transition: RasterPixelTransition

    def sample(self, source_rect: QRectF, pixel_size: QSize) -> QImage:
        """Return exact transitioned coverage on the requested sampling grid."""
        bounds = RasterBounds.from_qrect(source_rect.toAlignedRect())
        pixels = self.surface.capture_region(bounds)
        overlap = bounds.intersection(self.transition.patch_bounds)
        if overlap is not None:
            source_x = overlap.x - self.transition.patch_bounds.x
            source_y = overlap.y - self.transition.patch_bounds.y
            target_x = overlap.x - bounds.x
            target_y = overlap.y - bounds.y
            pixels[
                target_y : target_y + overlap.height,
                target_x : target_x + overlap.width,
            ] = self.transition.after_pixels[
                source_y : source_y + overlap.height,
                source_x : source_x + overlap.width,
            ]
        return project_coverage_image(
            coverage_image(pixels),
            bounds,
            source_rect,
            pixel_size,
        )


@dataclass(frozen=True, slots=True)
class _RetainedItemSampler:
    """Sample one immutable non-vector retained coverage contribution."""

    item: CoverageItem

    def sample(self, source_rect: QRectF, pixel_size: QSize) -> QImage:
        """Evaluate only the requested source region, then sample its density."""
        bounds = RasterBounds.from_qrect(source_rect.toAlignedRect())
        pixels = CoverageDocumentEvaluator().evaluate_item(self.item, bounds)
        image = coverage_image(pixels)
        return project_coverage_image(image, bounds, source_rect, pixel_size)


def _pair_revisions(first: int, second: int) -> int:
    """Return one collision-free scalar identity for two non-negative revisions."""
    total = max(0, int(first)) + max(0, int(second))
    return total * (total + 1) // 2 + max(0, int(second))
