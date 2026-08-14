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
"""Semantic-vector adapter for QPane's shared sampled-tile refinement."""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable, Hashable
from dataclasses import dataclass

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter, QTransform

from ..rendering.render_tile_geometry import RenderTileRequest
from ..rendering.render_tile_types import RenderTileProduct
from ..scene.raster import RasterBounds
from .drawing import draw_vector_document
from .model import VectorDocument
from .text_layout import SemanticTextLayoutCache


@dataclass(frozen=True, slots=True)
class VectorRenderTileSource:
    """Adapt one immutable vector revision to shared tile refinement."""

    document: VectorDocument
    revision_key: Hashable

    @property
    def source_kind(self) -> str:
        """Return the stable vector cache namespace."""
        return "vector"

    @property
    def source_id(self) -> uuid.UUID:
        """Return the stable vector-document identity."""
        return self.document.vector_id

    @property
    def bounds(self) -> RasterBounds:
        """Return zero-origin sampling bounds for the layer projector."""
        bounds = self.document.bounds
        return RasterBounds(0, 0, bounds.width, bounds.height)

    @property
    def fallback_key(self) -> Hashable:
        """Return exact semantic-vector content fallback identity."""
        return self.document.bounds, self.document.revision

    @property
    def detail_requires_idle_settle(self) -> bool:
        """Keep expensive exact rasterization behind GUI input continuity."""
        return True

    def render_tiles(
        self,
        requests: tuple[RenderTileRequest, ...],
        is_cancelled: Callable[[], bool],
    ) -> tuple[RenderTileProduct, ...]:
        """Rasterize one bounded batch and detach each antialiased core."""
        if not requests or is_cancelled():
            return ()
        scale = requests[0].key.scale
        sample_rect = QRectF(requests[0].paint_rect)
        for request in requests[1:]:
            sample_rect = sample_rect.united(request.paint_rect)
        document_bounds = self.document.bounds
        paint_rect = sample_rect.translated(
            float(document_bounds.x),
            float(document_bounds.y),
        )
        width = max(1, math.ceil(sample_rect.width() * scale))
        height = max(1, math.ceil(sample_rect.height() * scale))
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setTransform(
                QTransform(
                    scale,
                    0.0,
                    0.0,
                    scale,
                    -paint_rect.x() * scale,
                    -paint_rect.y() * scale,
                )
            )
            draw_vector_document(
                painter,
                self.document,
                None,
                SemanticTextLayoutCache(16 * 1024 * 1024),
            )
        finally:
            painter.end()
        products: list[RenderTileProduct] = []
        for request in requests:
            if is_cancelled():
                return ()
            paint = request.paint_rect
            x = round((paint.x() - sample_rect.x()) * scale)
            y = round((paint.y() - sample_rect.y()) * scale)
            width = max(1, math.ceil(paint.width() * scale))
            height = max(1, math.ceil(paint.height() * scale))
            detached = image.copy(x, y, width, height)
            core = request.source_rect
            products.append(
                RenderTileProduct(
                    request.key,
                    core,
                    detached,
                    QRectF(
                        (core.x() - paint.x()) * scale,
                        (core.y() - paint.y()) * scale,
                        core.width() * scale,
                        core.height() * scale,
                    ),
                )
            )
        return tuple(products)
