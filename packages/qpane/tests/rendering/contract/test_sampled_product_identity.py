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

"""Contract tests for immutable sampled tile product identity."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage

from qpane.sdk.scene import SampledTileRenderData


def test_sampled_product_identity_tracks_pixels_and_complete_geometry() -> None:
    """Identity must be cheap, copy-stable, and sensitive to product changes."""
    image = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(20, 40, 60, 255))
    tile = SampledTileRenderData(
        image,
        QRectF(0.0, 0.0, 64.0, 64.0),
        QRectF(1.0, 1.0, 62.0, 62.0),
        QRectF(2.0, 2.0, 60.0, 60.0),
        True,
    )
    initial_cache_key = tile.image.cacheKey()
    detached_handle = replace(tile, image=QImage(tile.image))
    changed_image = QImage(tile.image)
    changed_image.setPixelColor(0, 0, QColor(200, 30, 10, 255))
    changed_product = replace(tile, image=changed_image)
    changed_geometry = replace(
        tile,
        source_clip_rect=QRectF(3.0, 2.0, 59.0, 60.0),
    )

    assert tile.image.cacheKey() == initial_cache_key
    assert detached_handle.product_key == tile.product_key
    assert changed_product.product_key != tile.product_key
    assert changed_geometry.product_key != tile.product_key
    assert changed_geometry.geometry_key != tile.geometry_key
