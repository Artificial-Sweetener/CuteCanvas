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
"""Compile exact transient raster transitions for every pixel-edit domain."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QSize
from qpane.sdk.scene import (
    RasterLayerRenderItem,
    SampledLayerRenderItem,
    SceneLayerAssetKey,
    TransientRasterResolvedContribution,
    TransientSampledResolvedContribution,
)

from ..scene.pixel_fragments import RasterPixelFormat
from ..scene.pixel_transitions import RasterPixelTransition
from ..scene.source_capabilities import PixelPresentationOwner
from .sampled_transition_tiles import (
    SampledTransitionTileCompiler,
    sampled_tiles_cover_bounds,
)


class RasterTransitionRenderCompiler:
    """Present one canonical pixel transition through its source owner."""

    def __init__(self, presentations: PixelPresentationOwner) -> None:
        """Bind the sole source-presentation registry."""
        self._presentations = presentations
        self._sampled_tiles = SampledTransitionTileCompiler(presentations)
        self._resolved_key: (
            tuple[uuid.UUID, SceneLayerAssetKey, object, object, bool] | None
        ) = None
        self._resolved: (
            TransientRasterResolvedContribution
            | TransientSampledResolvedContribution
            | None
        ) = None

    def compile(
        self,
        *,
        session_id: uuid.UUID,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        pixel_format: RasterPixelFormat,
        transition: RasterPixelTransition,
        generation: object,
        item: RasterLayerRenderItem | SampledLayerRenderItem,
        retain_until_durable: bool = True,
    ) -> (
        TransientRasterResolvedContribution
        | TransientSampledResolvedContribution
        | None
    ):
        """Present one exact transition through an existing raster render item."""
        asset_key = raster_item_asset_key(item)
        sample_batch_key = (
            item.sample_batch_key if isinstance(item, SampledLayerRenderItem) else None
        )
        key = (
            session_id,
            asset_key,
            generation,
            sample_batch_key,
            retain_until_durable,
        )
        if key == self._resolved_key:
            return self._resolved
        if isinstance(item, SampledLayerRenderItem):
            resolved = self._compile_sampled(
                session_id=session_id,
                scene_id=scene_id,
                layer_id=layer_id,
                pixel_format=pixel_format,
                transition=transition,
                transition_key=(session_id, asset_key, generation),
                item=item,
                retain_until_durable=retain_until_durable,
            )
        else:
            resolved = self._compile_patch(
                session_id=session_id,
                scene_id=scene_id,
                layer_id=layer_id,
                pixel_format=pixel_format,
                transition=transition,
                item=item,
                retain_until_durable=retain_until_durable,
            )
        self._resolved_key = key
        self._resolved = resolved
        return resolved

    def _compile_patch(
        self,
        *,
        session_id: uuid.UUID,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        pixel_format: RasterPixelFormat,
        transition: RasterPixelTransition,
        item: RasterLayerRenderItem | SampledLayerRenderItem,
        retain_until_durable: bool,
    ) -> TransientRasterResolvedContribution | None:
        """Present one transition patch independently of durable source bounds."""
        scale_x, scale_y = raster_item_sample_scale(item)
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
        return TransientRasterResolvedContribution(
            session_id=session_id,
            scene_id=scene_id,
            layer_id=layer_id,
            source_asset_key=raster_item_asset_key(item),
            source_image=replacement,
            source_bounds=transition.patch_bounds,
            retain_until_durable=retain_until_durable,
        )

    def _compile_sampled(
        self,
        *,
        session_id: uuid.UUID,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        pixel_format: RasterPixelFormat,
        transition: RasterPixelTransition,
        transition_key: tuple[uuid.UUID, SceneLayerAssetKey, object],
        item: SampledLayerRenderItem,
        retain_until_durable: bool,
    ) -> (
        TransientRasterResolvedContribution
        | TransientSampledResolvedContribution
        | None
    ):
        """Patch one edit into the sampled source's exact tile products."""
        sampled_bounds = item.descriptor.raster_bounds
        if (
            sampled_bounds is None
            or not sampled_bounds.contains(transition.patch_bounds)
            or not sampled_tiles_cover_bounds(item.tiles, transition.patch_bounds)
        ):
            return self._compile_patch(
                session_id=session_id,
                scene_id=scene_id,
                layer_id=layer_id,
                pixel_format=pixel_format,
                transition=transition,
                item=item,
                retain_until_durable=retain_until_durable,
            )
        scale_x, scale_y = raster_item_sample_scale(item)
        resolved_tiles = self._sampled_tiles.compile(
            transition_key=transition_key,
            pixel_format=pixel_format,
            transition=transition,
            item=item,
            sampled_bounds=sampled_bounds,
            scale_x=scale_x,
            scale_y=scale_y,
        )
        if resolved_tiles is None:
            return None
        return TransientSampledResolvedContribution(
            session_id=session_id,
            scene_id=scene_id,
            layer_id=layer_id,
            source_asset_key=raster_item_asset_key(item),
            source_bounds=transition.patch_bounds,
            tiles=resolved_tiles,
            sampled_raster_bounds=sampled_bounds,
            sampled_source_size=item.source_size,
            retain_until_durable=retain_until_durable,
        )


def raster_item_asset_key(
    item: RasterLayerRenderItem | SampledLayerRenderItem,
) -> SceneLayerAssetKey:
    """Return stable scene-layer source identity for any rasterized product."""
    if isinstance(item, RasterLayerRenderItem):
        return item.asset_key
    descriptor = item.descriptor
    return SceneLayerAssetKey(
        scene_id=descriptor.scene_id,
        layer_id=descriptor.layer_id,
        source_id=descriptor.source.resource_id,
        source_kind=descriptor.source.kind,
        source_revision=descriptor.source_revision,
    )


def raster_item_sample_scale(
    item: RasterLayerRenderItem | SampledLayerRenderItem,
) -> tuple[float, float]:
    """Return current product pixels per source unit on each axis."""
    if isinstance(item, RasterLayerRenderItem):
        bounds = item.descriptor.raster_bounds
        if bounds is None or bounds.width <= 0 or bounds.height <= 0:
            return 1.0, 1.0
        return (
            item.source_image.width() / bounds.width,
            item.source_image.height() / bounds.height,
        )
    for tile in item.tiles:
        if tile.source_rect.width() > 0.0 and tile.source_rect.height() > 0.0:
            return (
                tile.image_source_rect.width() / tile.source_rect.width(),
                tile.image_source_rect.height() / tile.source_rect.height(),
            )
    return 1.0, 1.0


__all__ = [
    "RasterTransitionRenderCompiler",
    "raster_item_asset_key",
    "raster_item_sample_scale",
]
