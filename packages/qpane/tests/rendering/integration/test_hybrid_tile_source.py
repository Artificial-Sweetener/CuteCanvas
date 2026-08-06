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
"""Verify bounded hybrid tile-source fast paths."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QColor, QImage
from qpane.hybrid.model import (
    HybridDocument,
    HybridPresentationStyle,
    HybridRasterPrimitive,
)
from qpane.hybrid.tile_source import HybridRenderTileSource
from qpane.rendering.render_tile_geometry import RenderTileKey, RenderTileRequest
from qpane.scene.raster import RasterBounds


class _RejectingSampler:
    """Fail if an out-of-region primitive is sampled."""

    def sample(self, source_rect: QRectF, pixel_size: QSize) -> QImage:
        """Reject work that the tile-source bounds gate must avoid."""
        del source_rect, pixel_size
        raise AssertionError("non-overlapping hybrid primitive was sampled")


def test_non_overlapping_hybrid_batch_returns_transparent_tiles() -> None:
    """Avoid allocating and colorizing one batch with no possible coverage."""
    source_id = uuid.uuid4()
    document = HybridDocument(
        source_id,
        RasterBounds(0, 0, 1024, 1024),
        (
            HybridRasterPrimitive(
                uuid.uuid4(),
                RasterBounds(2048, 2048, 1, 1),
                _RejectingSampler(),
            ),
        ),
    )
    source = HybridRenderTileSource(
        document,
        HybridPresentationStyle(QColor("magenta")),
    )
    key = RenderTileKey(
        "hybrid",
        source_id,
        source.fallback_key,
        source.revision_key,
        2.0,
        0,
        0,
    )
    request = RenderTileRequest(
        key,
        QRectF(0.0, 0.0, 64.0, 64.0),
        QRectF(-1.0, -1.0, 66.0, 66.0),
    )

    products = source.render_tiles((request,), lambda: False)

    assert len(products) == 1
    assert products[0].image.size() == QSize(132, 132)
    assert products[0].image.pixelColor(64, 64).alpha() == 0
    assert products[0].source_rect == request.source_rect
    assert products[0].image_source_rect == QRectF(2.0, 2.0, 128.0, 128.0)


def test_presentation_style_participates_in_shared_tile_identity() -> None:
    """One hybrid source must not reuse pixels colorized for another view."""
    document = HybridDocument(
        uuid.uuid4(),
        RasterBounds(0, 0, 64, 64),
    )
    white = HybridRenderTileSource(
        document,
        HybridPresentationStyle(QColor("white")),
    )
    magenta = HybridRenderTileSource(
        document,
        HybridPresentationStyle(QColor("magenta")),
    )

    assert white.revision_key != magenta.revision_key
    assert white.fallback_key != magenta.fallback_key
