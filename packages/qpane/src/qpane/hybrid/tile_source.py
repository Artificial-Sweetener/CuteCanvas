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

import numpy as np
from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QImage

from ..raster.image_conversion import (
    numpy_to_qimage_argb32,
    qimage_to_numpy_grayscale8,
)
from ..rendering.render_tile_geometry import RenderTileRequest
from ..rendering.render_tile_types import RenderTileProduct
from ..scene.raster import RasterBounds
from .evaluation import HybridDocumentEvaluator
from .model import HybridDocument, HybridPresentationStyle


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
        return self.document.revision, self.presentation_revision

    @property
    def fallback_key(self) -> Hashable:
        """Return source geometry shared by visually compatible revisions."""
        return self.document.bounds

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
        scale = requests[0].key.scale
        batch_rect = QRectF(requests[0].paint_rect)
        for request in requests[1:]:
            batch_rect = batch_rect.united(request.paint_rect)
        document_rect = _to_document_rect(batch_rect, self.document.bounds)
        batch_size = _sample_size(batch_rect, scale)
        coverage = HybridDocumentEvaluator().evaluate(
            self.document,
            document_rect,
            batch_size,
        )
        if is_cancelled():
            return ()
        presented = _present_coverage(coverage, self.style)
        products: list[RenderTileProduct] = []
        for request in requests:
            if is_cancelled():
                return ()
            paint = request.paint_rect
            sample_rect = _pixel_rect(paint, batch_rect, scale)
            detached = presented.copy(sample_rect.toAlignedRect())
            core = request.source_rect
            image_source_rect = _pixel_rect(core, paint, scale)
            products.append(
                RenderTileProduct(
                    request.key,
                    core,
                    detached,
                    image_source_rect,
                )
            )
        return tuple(products)


def _to_document_rect(rect: QRectF, bounds: RasterBounds) -> QRectF:
    """Translate zero-origin sampling coordinates into document coordinates."""
    return rect.translated(float(bounds.x), float(bounds.y))


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


def _present_coverage(image: QImage, style: HybridPresentationStyle) -> QImage:
    """Return premultiplied color pixels for grayscale coverage."""
    coverage = qimage_to_numpy_grayscale8(image)
    alpha = coverage.astype(np.uint16)
    color = style.color
    output = np.empty((*coverage.shape, 4), dtype=np.uint8)
    output[..., 0] = ((alpha * color.blue()) // 255).astype(np.uint8)
    output[..., 1] = ((alpha * color.green()) // 255).astype(np.uint8)
    output[..., 2] = ((alpha * color.red()) // 255).astype(np.uint8)
    output[..., 3] = coverage
    if style.outline_color is not None:
        border = _outer_border(coverage)
        border_alpha = border.astype(np.uint16)
        outline = style.outline_color
        output[..., 0] = np.maximum(
            output[..., 0],
            ((border_alpha * outline.blue()) // 255).astype(np.uint8),
        )
        output[..., 1] = np.maximum(
            output[..., 1],
            ((border_alpha * outline.green()) // 255).astype(np.uint8),
        )
        output[..., 2] = np.maximum(
            output[..., 2],
            ((border_alpha * outline.red()) // 255).astype(np.uint8),
        )
        output[..., 3] = np.maximum(output[..., 3], border)
    return numpy_to_qimage_argb32(output)


def _outer_border(coverage: np.ndarray) -> np.ndarray:
    """Return one-pixel outer coverage without crossing tile bleed."""
    padded = np.pad(coverage, 1, mode="constant")
    expanded = np.zeros_like(coverage)
    for y in range(3):
        for x in range(3):
            expanded = np.maximum(
                expanded,
                padded[y : y + coverage.shape[0], x : x + coverage.shape[1]],
            )
    return np.maximum(expanded.astype(np.int16) - coverage, 0).astype(np.uint8)
