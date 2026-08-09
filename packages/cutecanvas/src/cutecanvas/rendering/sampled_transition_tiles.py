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

"""Incrementally present pixel transitions on current sampled tile products."""

from __future__ import annotations

import math
import uuid
from collections.abc import Hashable

from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QImage, QPainter, QRegion
from qpane.sdk.scene import (
    RasterBounds,
    SampledLayerRenderItem,
    SampledTileRenderData,
    SceneLayerAssetKey,
)

from ..scene.pixel_fragments import RasterPixelFormat
from ..scene.pixel_transitions import RasterPixelTransition
from ..scene.source_capabilities import PixelPresentationOwner, PixelSampleGeometry


class SampledTransitionTileCompiler:
    """Resolve and retain only the current viewport's edited sampled tiles."""

    def __init__(self, presentations: PixelPresentationOwner) -> None:
        """Bind source-owned presentation and initialize an empty bounded cache."""
        self._presentations = presentations
        self._transition_key: tuple[uuid.UUID, SceneLayerAssetKey, object] | None = None
        self._tiles: dict[Hashable, SampledTileRenderData] = {}

    def compile(
        self,
        *,
        transition_key: tuple[uuid.UUID, SceneLayerAssetKey, object],
        pixel_format: RasterPixelFormat,
        transition: RasterPixelTransition,
        item: SampledLayerRenderItem,
        sampled_bounds: RasterBounds,
        scale_x: float,
        scale_y: float,
    ) -> tuple[SampledTileRenderData, ...] | None:
        """Return edited products for exactly the current atomic sampled batch."""
        if transition_key != self._transition_key:
            self._transition_key = transition_key
            self._tiles.clear()

        source_keys = item.sample_batch_key
        current: dict[Hashable, SampledTileRenderData] = {}
        missing: list[tuple[Hashable, SampledTileRenderData]] = []
        for source_key, tile in zip(source_keys, item.tiles, strict=True):
            resolved = self._tiles.get(source_key)
            if resolved is None:
                missing.append((source_key, tile))
            else:
                current[source_key] = resolved

        if missing:
            resolved_missing = self._present_missing(
                tuple(tile for _key, tile in missing),
                pixel_format=pixel_format,
                transition=transition,
                item=item,
                sampled_bounds=sampled_bounds,
                scale_x=scale_x,
                scale_y=scale_y,
            )
            if resolved_missing is None:
                return None
            current.update(
                (source_key, resolved)
                for (source_key, _tile), resolved in zip(
                    missing,
                    resolved_missing,
                    strict=True,
                )
            )

        self._tiles = current
        return tuple(current[source_key] for source_key in source_keys)

    def _present_missing(
        self,
        tiles: tuple[SampledTileRenderData, ...],
        *,
        pixel_format: RasterPixelFormat,
        transition: RasterPixelTransition,
        item: SampledLayerRenderItem,
        sampled_bounds: RasterBounds,
        scale_x: float,
        scale_y: float,
    ) -> tuple[SampledTileRenderData, ...] | None:
        """Present only newly demanded source products for one transition."""
        sample_geometry = tuple(
            _sample_geometry(
                tile,
                scale_x,
                scale_y,
                sampled_bounds.x,
                sampled_bounds.y,
            )
            for tile in tiles
        )
        exact_samples = self._presentations.present_transition_samples(
            item.descriptor.source,
            pixel_format,
            transition,
            sample_geometry,
        )
        if exact_samples is not None and len(exact_samples) == len(tiles):
            return tuple(
                SampledTileRenderData(
                    image,
                    tile.source_rect,
                    tile.image_source_rect,
                    tile.source_clip_rect,
                    tile.integer_origin_sampling,
                )
                for tile, image in zip(tiles, exact_samples, strict=True)
            )

        replacement_size = QSize(
            max(1, round(transition.patch_bounds.width * scale_x)),
            max(1, round(transition.patch_bounds.height * scale_y)),
        )
        replacement = self._presentations.present_pixels(
            item.descriptor.source,
            pixel_format,
            transition.after_pixels,
            replacement_size,
        )
        if replacement is None or replacement.isNull():
            return None
        return tuple(
            _replace_sampled_tile(
                tile,
                transition.patch_bounds,
                replacement,
                scale_x,
                scale_y,
                sampled_bounds.x,
                sampled_bounds.y,
            )
            for tile in tiles
        )


def sampled_tiles_cover_bounds(
    tiles: tuple[SampledTileRenderData, ...],
    bounds: RasterBounds,
) -> bool:
    """Return whether sampled tile cores cover every pixel in ``bounds``."""
    coverage = QRegion()
    for tile in tiles:
        source_rect = tile.source_rect
        left = math.ceil(source_rect.left())
        top = math.ceil(source_rect.top())
        right = math.floor(source_rect.left() + source_rect.width())
        bottom = math.floor(source_rect.top() + source_rect.height())
        if right > left and bottom > top:
            coverage += QRegion(left, top, right - left, bottom - top)
    return coverage.contains(bounds.to_qrect())


def _replace_sampled_tile(
    tile: SampledTileRenderData,
    patch_bounds: RasterBounds,
    replacement: QImage,
    scale_x: float,
    scale_y: float,
    source_origin_x: int,
    source_origin_y: int,
) -> SampledTileRenderData:
    """Return one sampled tile with a transient source patch applied in place."""
    image = tile.image.copy()
    paint_origin_x = (
        source_origin_x + tile.source_rect.x() - tile.image_source_rect.x() / scale_x
    )
    paint_origin_y = (
        source_origin_y + tile.source_rect.y() - tile.image_source_rect.y() / scale_y
    )
    target = QRectF(
        (patch_bounds.x - paint_origin_x) * scale_x,
        (patch_bounds.y - paint_origin_y) * scale_y,
        patch_bounds.width * scale_x,
        patch_bounds.height * scale_y,
    )
    painter = QPainter(image)
    try:
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.drawImage(target, replacement, QRectF(replacement.rect()))
    finally:
        painter.end()
    return SampledTileRenderData(
        image,
        tile.source_rect,
        tile.image_source_rect,
        tile.source_clip_rect,
        tile.integer_origin_sampling,
    )


def _sample_geometry(
    tile: SampledTileRenderData,
    scale_x: float,
    scale_y: float,
    source_origin_x: int,
    source_origin_y: int,
) -> PixelSampleGeometry:
    """Recover one sampled tile's complete source footprint including bleed."""
    source_rect = QRectF(
        source_origin_x + tile.source_rect.x() - tile.image_source_rect.x() / scale_x,
        source_origin_y + tile.source_rect.y() - tile.image_source_rect.y() / scale_y,
        tile.image.width() / scale_x,
        tile.image.height() / scale_y,
    )
    return PixelSampleGeometry(source_rect, tile.image.size())


__all__ = ["SampledTransitionTileCompiler", "sampled_tiles_cover_bounds"]
