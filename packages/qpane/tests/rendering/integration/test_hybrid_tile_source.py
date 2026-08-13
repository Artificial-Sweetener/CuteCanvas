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


class _RecordingSampler:
    """Return opaque coverage while recording exact sampled regions."""

    def __init__(self) -> None:
        """Create an empty sampling record."""
        self.calls: list[tuple[QRectF, QSize]] = []

    def sample(self, source_rect: QRectF, pixel_size: QSize) -> QImage:
        """Record and return one exact grayscale sample."""
        self.calls.append((QRectF(source_rect), QSize(pixel_size)))
        image = QImage(pixel_size, QImage.Format.Format_Grayscale8)
        image.fill(255)
        return image


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


def test_hybrid_batch_never_samples_the_gap_between_distant_tiles() -> None:
    """Cache-filtered tile batches must not amplify work across empty spans."""
    sampler = _RecordingSampler()
    source_id = uuid.uuid4()
    document = HybridDocument(
        source_id,
        RasterBounds(0, 0, 4096, 4096),
        (
            HybridRasterPrimitive(
                uuid.uuid4(),
                RasterBounds(0, 0, 4096, 4096),
                sampler,
            ),
        ),
    )
    source = HybridRenderTileSource(
        document,
        HybridPresentationStyle(QColor("white")),
    )
    requests = (
        _request(source, column=0, paint_rect=QRectF(0.0, 0.0, 66.0, 66.0)),
        _request(source, column=40, paint_rect=QRectF(2558.0, 0.0, 66.0, 66.0)),
    )

    products = source.render_tiles(requests, lambda: False)

    assert tuple(product.key for product in products) == tuple(
        request.key for request in requests
    )
    assert len(sampler.calls) == 2
    assert {size for _, size in sampler.calls} == {QSize(66, 66)}


def test_hybrid_batch_retains_shared_sampling_for_adjacent_tile_rectangle() -> None:
    """Adjacent tiles must retain one efficient shared evaluation."""
    sampler = _RecordingSampler()
    source_id = uuid.uuid4()
    document = HybridDocument(
        source_id,
        RasterBounds(0, 0, 256, 256),
        (
            HybridRasterPrimitive(
                uuid.uuid4(),
                RasterBounds(0, 0, 256, 256),
                sampler,
            ),
        ),
    )
    source = HybridRenderTileSource(
        document,
        HybridPresentationStyle(QColor("white")),
    )
    requests = (
        _request(source, column=0, row=0, paint_rect=QRectF(0.0, 0.0, 66.0, 66.0)),
        _request(source, column=1, row=0, paint_rect=QRectF(64.0, 0.0, 66.0, 66.0)),
        _request(source, column=0, row=1, paint_rect=QRectF(0.0, 64.0, 66.0, 66.0)),
        _request(source, column=1, row=1, paint_rect=QRectF(64.0, 64.0, 66.0, 66.0)),
    )

    products = source.render_tiles(requests, lambda: False)

    assert len(products) == 4
    assert sampler.calls == [(QRectF(0.0, 0.0, 130.0, 130.0), QSize(130, 130))]


def _request(
    source: HybridRenderTileSource,
    *,
    column: int,
    row: int = 0,
    paint_rect: QRectF,
) -> RenderTileRequest:
    """Build one stable request for hybrid batching tests."""
    key = RenderTileKey(
        source.source_kind,
        source.source_id,
        source.fallback_key,
        source.revision_key,
        1.0,
        column,
        row,
    )
    return RenderTileRequest(key, QRectF(paint_rect), QRectF(paint_rect))
