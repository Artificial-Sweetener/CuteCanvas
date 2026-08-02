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

from PySide6.QtCore import QRectF, QSize

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
        return self.document.revision, self.presentation_revision

    @property
    def fallback_key(self) -> Hashable:
        """Return exact content and presentation fallback identity."""
        return (
            self.document.bounds,
            self.document.revision,
            self.presentation_revision,
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
        scale = requests[0].key.scale
        batch_rect = QRectF(requests[0].paint_rect)
        for request in requests[1:]:
            batch_rect = batch_rect.united(request.paint_rect)
        document_rect = _to_document_rect(batch_rect, self.document.bounds)
        batch_size = _sample_size(batch_rect, scale)
        coverage = HybridDocumentEvaluator().evaluate_pixels(
            self.document,
            document_rect,
            batch_size,
        )
        if is_cancelled():
            return ()
        presented = present_hybrid_pixels(coverage, self.style)
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
