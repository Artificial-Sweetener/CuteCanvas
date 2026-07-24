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

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize
from PySide6.QtGui import QImage, QPainter
from qpane import (
    HybridCombineMode,
    HybridDocument,
    HybridPresentationStyle,
    HybridRasterPrimitive,
    HybridSource,
    HybridVectorPrimitive,
    RasterBounds,
)

from cutecanvas.coverage import CoverageDocumentEvaluator
from cutecanvas.coverage.document import CoverageItem, VectorCoverageItem
from cutecanvas.coverage.surface import CoverageSurface

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
    ) -> HybridSource | None:
        """Return one immutable QPane source without evaluating visible pixels."""
        bounds = layer.coverage.source_bounds()
        if bounds is None:
            return None
        primitives: list[_HybridPrimitive] = []
        raster_bounds = layer.coverage.raster.content_bounds()
        if raster_bounds is not None:
            primitives.append(
                HybridRasterPrimitive(
                    uuid.uuid5(layer.mask_id, "authoritative-raster"),
                    raster_bounds,
                    _SurfaceSampler(layer.coverage.raster),
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
class _SurfaceSampler:
    """Sample a thread-safe sparse coverage surface in document coordinates."""

    surface: CoverageSurface

    def sample(self, source_rect: QRectF, pixel_size: QSize) -> QImage:
        """Return one filtered grayscale sample without dense-gap allocation."""
        bounds = RasterBounds.from_qrect(source_rect.toAlignedRect())
        image = _coverage_image(self.surface.capture_region(bounds))
        return _project_sample(image, bounds, source_rect, pixel_size)


@dataclass(frozen=True, slots=True)
class _RetainedItemSampler:
    """Sample one immutable non-vector retained coverage contribution."""

    item: CoverageItem

    def sample(self, source_rect: QRectF, pixel_size: QSize) -> QImage:
        """Evaluate only the requested source region, then sample its density."""
        bounds = RasterBounds.from_qrect(source_rect.toAlignedRect())
        pixels = CoverageDocumentEvaluator().evaluate_item(self.item, bounds)
        image = _coverage_image(pixels)
        return _project_sample(image, bounds, source_rect, pixel_size)


def _project_sample(
    image: QImage,
    image_bounds: RasterBounds,
    source_rect: QRectF,
    pixel_size: QSize,
) -> QImage:
    """Project an integer-bounded grayscale capture to an exact sample rectangle."""
    exact_rect = QRectF(
        float(image_bounds.x),
        float(image_bounds.y),
        float(image_bounds.width),
        float(image_bounds.height),
    )
    if source_rect == exact_rect and pixel_size == image.size():
        return image
    target = QImage(pixel_size, QImage.Format_Grayscale8)
    target.fill(0)
    painter = QPainter(target)
    try:
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        scale_x = pixel_size.width() / source_rect.width()
        scale_y = pixel_size.height() / source_rect.height()
        painter.scale(scale_x, scale_y)
        painter.translate(-source_rect.x(), -source_rect.y())
        painter.drawImage(QPointF(image_bounds.x, image_bounds.y), image)
    finally:
        painter.end()
    return target


def _coverage_image(pixels: np.ndarray) -> QImage:
    """Detach one contiguous coverage array into a grayscale Qt image."""
    contiguous = memoryview(pixels)
    height, width = contiguous.shape
    return QImage(
        contiguous,
        width,
        height,
        width,
        QImage.Format.Format_Grayscale8,
    ).copy()


def _pair_revisions(first: int, second: int) -> int:
    """Return one collision-free scalar identity for two non-negative revisions."""
    total = max(0, int(first)) + max(0, int(second))
    return total * (total + 1) // 2 + max(0, int(second))
