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
"""Bounded cached atlases for phase-stable sampled tile presentation."""

from __future__ import annotations

import uuid
from collections.abc import Hashable
from math import isclose

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QImage, QPainter

from ..scene.identity import SourceRenderAssetKey, source_render_asset_key
from ..scene.render_plan import SampledTileRenderData
from .raster_products import RasterRenderProductStore
from .storage_allocation import checked_argb_image, checked_painter

_MAX_ATLAS_PIXELS = 4 * 1024 * 1024


def compact_native_sampled_tiles(
    *,
    products: RasterRenderProductStore,
    asset_key: SourceRenderAssetKey,
    product_identity: Hashable,
    atlas_rect: QRectF,
    tiles: tuple[SampledTileRenderData, ...],
) -> SampledTileRenderData | None:
    """Return one cached native atlas on the supplied source lattice."""
    if (
        not tiles
        or not _is_integral_rect(atlas_rect)
        or atlas_rect.width() * atlas_rect.height() > _MAX_ATLAS_PIXELS
        or any(not _is_native_tile(tile) for tile in tiles)
    ):
        return None
    covered_pixels = sum(
        tile.source_rect.intersected(atlas_rect).width()
        * tile.source_rect.intersected(atlas_rect).height()
        for tile in tiles
    )
    if covered_pixels < atlas_rect.width() * atlas_rect.height():
        return None
    derived_id = uuid.uuid5(
        asset_key.source_id,
        f"sampled-atlas:{product_identity!r}:{atlas_rect.getRect()!r}",
    )
    atlas_key = source_render_asset_key(
        source_id=derived_id,
        source_kind=f"{asset_key.source_kind}-sampled-atlas",
        revision=asset_key.source_revision,
        source_path=asset_key.source_path,
    )
    width = round(atlas_rect.width())
    atlas = products.sampled_image(
        asset_key=atlas_key,
        source_width=width,
        target_width=float(width),
        producer=lambda _scale: _compose_atlas(atlas_rect, tiles),
    )
    if atlas is None or atlas.isNull():
        return None
    return SampledTileRenderData(
        atlas,
        atlas_rect,
        QRectF(atlas.rect()),
        integer_origin_sampling=True,
    )


def _compose_atlas(
    atlas_rect: QRectF,
    tiles: tuple[SampledTileRenderData, ...],
) -> QImage:
    """Copy native tile cores onto one transparent source-anchored image."""
    atlas = checked_argb_image(
        QSize(round(atlas_rect.width()), round(atlas_rect.height())),
    )
    atlas.fill(Qt.GlobalColor.transparent)
    painter = checked_painter(atlas, "sampled atlas composition")
    painter.setCompositionMode(QPainter.CompositionMode_Source)
    try:
        for tile in tiles:
            core = tile.source_rect.intersected(atlas_rect)
            if core.isEmpty():
                continue
            destination = core.translated(-atlas_rect.x(), -atlas_rect.y())
            source = QRectF(
                tile.image_source_rect.x() + core.x() - tile.source_rect.x(),
                tile.image_source_rect.y() + core.y() - tile.source_rect.y(),
                core.width(),
                core.height(),
            )
            painter.drawImage(destination, tile.image, source)
    finally:
        painter.end()
    return atlas


def _is_native_tile(tile: SampledTileRenderData) -> bool:
    """Return whether one tile carries one image pixel per source pixel."""
    return (
        _is_integral_rect(tile.source_rect)
        and _is_integral_rect(tile.image_source_rect)
        and isclose(tile.source_rect.width(), tile.image_source_rect.width())
        and isclose(tile.source_rect.height(), tile.image_source_rect.height())
    )


def _is_integral_rect(rect: QRectF) -> bool:
    """Return whether every rectangle component lies on an integer boundary."""
    return all(
        isclose(value, round(value), rel_tol=0.0, abs_tol=1e-9)
        for value in rect.getRect()
    )
