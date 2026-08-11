#    QPane - High-performance PySide6 image viewer
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
"""Hybrid-document adapter for shared sampled-tile refinement."""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from functools import lru_cache

from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QImage

from ..rendering.render_tile_geometry import RenderTileRequest
from ..rendering.render_tile_types import RenderTileProduct
from ..scene.raster import RasterBounds
from .evaluation import HybridDocumentEvaluator
from .model import HybridDocument, HybridPresentationStyle
from .presentation import present_hybrid_pixels


@dataclass(frozen=True, slots=True)
class HybridRenderTileSource:
    """Adapt one immutable hybrid revision to shared tile refinement."""

    document: HybridDocument
    style: HybridPresentationStyle
    presentation_revision: int = 0

    @property
    def source_kind(self) -> str:
        """Return the stable hybrid cache namespace."""
        return "hybrid"

    @property
    def source_id(self) -> uuid.UUID:
        """Return the stable hybrid-document identity."""
        return self.document.source_id

    @property
    def revision_key(self) -> Hashable:
        """Return content plus presentation revision identity."""
        return (
            self.document.revision,
            self.presentation_revision,
            _presentation_key(self.style),
        )

    @property
    def fallback_key(self) -> Hashable:
        """Return exact content and presentation fallback identity."""
        return (
            self.document.bounds,
            self.document.revision,
            self.presentation_revision,
            _presentation_key(self.style),
        )

    @property
    def bounds(self) -> RasterBounds:
        """Return zero-origin sampling bounds for the layer projector."""
        bounds = self.document.bounds
        return RasterBounds(0, 0, bounds.width, bounds.height)

    def render_tiles(
        self,
        requests: tuple[RenderTileRequest, ...],
        is_cancelled: Callable[[], bool],
    ) -> tuple[RenderTileProduct, ...]:
        """Evaluate and present one complete visible tile batch."""
        if not requests or is_cancelled():
            return ()
        products_by_key: dict[Hashable, RenderTileProduct] = {}
        for batch in _bounded_batches(requests):
            if is_cancelled():
                return ()
            for product in self._render_batch(batch, is_cancelled):
                products_by_key[product.key] = product
        if is_cancelled():
            return ()
        return tuple(products_by_key[request.key] for request in requests)

    def _render_batch(
        self,
        batch: _HybridTileBatch,
        is_cancelled: Callable[[], bool],
    ) -> tuple[RenderTileProduct, ...]:
        """Evaluate one spatially compact group of same-scale tiles."""
        requests = batch.requests
        scale = requests[0].key.scale
        document_rect = _to_document_rect(batch.paint_rect, self.document.bounds)
        if not _has_primitive_overlap(self.document, document_rect):
            return tuple(_transparent_product(request, scale) for request in requests)
        coverage = HybridDocumentEvaluator().evaluate_pixels(
            self.document,
            document_rect,
            _sample_size(batch.paint_rect, scale),
        )
        if is_cancelled():
            return ()
        presented = present_hybrid_pixels(coverage, self.style)
        products: list[RenderTileProduct] = []
        for request in requests:
            if is_cancelled():
                return ()
            paint = request.paint_rect
            sample_rect = _pixel_rect(paint, batch.paint_rect, scale)
            products.append(
                RenderTileProduct(
                    request.key,
                    request.source_rect,
                    presented.copy(sample_rect.toAlignedRect()),
                    _pixel_rect(request.source_rect, paint, scale),
                )
            )
        return tuple(products)

    def immediate_products(
        self,
        requests: tuple[RenderTileRequest, ...],
    ) -> tuple[RenderTileProduct, ...] | None:
        """Return transparent products when bounded geometry proves no coverage."""
        if not requests:
            return ()
        scale = requests[0].key.scale
        batch_rect = QRectF(requests[0].paint_rect)
        for request in requests[1:]:
            batch_rect = batch_rect.united(request.paint_rect)
        document_rect = _to_document_rect(batch_rect, self.document.bounds)
        if _has_primitive_overlap(self.document, document_rect):
            return None
        return tuple(_transparent_product(request, scale) for request in requests)


def _to_document_rect(rect: QRectF, bounds: RasterBounds) -> QRectF:
    """Translate zero-origin sampling coordinates into document coordinates."""
    return rect.translated(float(bounds.x), float(bounds.y))


@dataclass(frozen=True, slots=True)
class _HybridTileBatch:
    """Group tiles whose shared sample does not amplify raster work."""

    requests: tuple[RenderTileRequest, ...]
    paint_rect: QRectF
    sample_area: int


def _bounded_batches(
    requests: tuple[RenderTileRequest, ...],
) -> tuple[_HybridTileBatch, ...]:
    """Combine spatial tiles only while their union reduces sampled pixels."""
    scale = requests[0].key.scale
    batches = [
        _HybridTileBatch(
            (request,),
            QRectF(request.paint_rect),
            _sample_area(request.paint_rect, scale),
        )
        for request in requests
    ]
    while True:
        best_merge: tuple[int, int, QRectF, int] | None = None
        best_saving = 0
        for left_index, left in enumerate(batches):
            for right_index in range(left_index + 1, len(batches)):
                right = batches[right_index]
                united = left.paint_rect.united(right.paint_rect)
                united_area = _sample_area(united, scale)
                saving = left.sample_area + right.sample_area - united_area
                if saving >= best_saving:
                    best_saving = saving
                    best_merge = (left_index, right_index, united, united_area)
        if best_merge is None:
            return tuple(batches)
        left_index, right_index, united, united_area = best_merge
        left = batches[left_index]
        right = batches[right_index]
        batches[left_index] = _HybridTileBatch(
            left.requests + right.requests,
            united,
            united_area,
        )
        batches.pop(right_index)


def _sample_area(rect: QRectF, scale: float) -> int:
    """Return exact allocated grayscale pixels for one sample rectangle."""
    size = _sample_size(rect, scale)
    return size.width() * size.height()


def _sample_size(rect: QRectF, scale: float) -> QSize:
    """Return a positive integer sample size for one source rectangle."""
    return QSize(
        max(1, math.ceil(rect.width() * scale)),
        max(1, math.ceil(rect.height() * scale)),
    )


def _pixel_rect(rect: QRectF, origin: QRectF, scale: float) -> QRectF:
    """Map one source rectangle into a sampled image coordinate space."""
    return QRectF(
        (rect.x() - origin.x()) * scale,
        (rect.y() - origin.y()) * scale,
        rect.width() * scale,
        rect.height() * scale,
    )


def _has_primitive_overlap(document: HybridDocument, source_rect: QRectF) -> bool:
    """Return whether any bounded primitive can affect the sampled region."""
    return any(
        not QRectF(
            primitive.bounds.x,
            primitive.bounds.y,
            primitive.bounds.width,
            primitive.bounds.height,
        )
        .intersected(source_rect)
        .isEmpty()
        for primitive in document.primitives
    )


def _transparent_product(
    request: RenderTileRequest,
    scale: float,
) -> RenderTileProduct:
    """Return one transparent tile without evaluating an empty hybrid region."""
    size = _sample_size(request.paint_rect, scale)
    image = QImage(_transparent_image(size.width(), size.height()))
    return RenderTileProduct(
        request.key,
        request.source_rect,
        image,
        _pixel_rect(request.source_rect, request.paint_rect, scale),
    )


def _presentation_key(
    style: HybridPresentationStyle,
) -> tuple[int, int | None]:
    """Return the exact 8-bit style identity used by presented tile pixels."""
    return (
        int(style.color.rgba()),
        None if style.outline_color is None else int(style.outline_color.rgba()),
    )


@lru_cache(maxsize=32)
def _transparent_image(width: int, height: int) -> QImage:
    """Return one implicitly shared immutable transparent tile allocation."""
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(0)
    return image
