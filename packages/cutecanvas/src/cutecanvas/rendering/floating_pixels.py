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
"""Compile stable lifted-pixel products for transient scene composition."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QImage, QPainter
from qpane.sdk.raster import (
    numpy_to_qimage_argb32,
    numpy_to_qimage_grayscale8_at_size,
    qimage_to_numpy_grayscale8,
)
from qpane.sdk.scene import (
    RasterBounds,
    RasterLayerRenderItem,
    SampledLayerRenderItem,
    SampledTileRenderData,
    SceneLayerAssetKey,
    SceneRenderItem,
    TransientRasterContribution,
    TransientRasterResolvedContribution,
    TransientRasterTransformContribution,
    TransientSampledResolvedContribution,
)

from ..scene.pixel_fragments import RasterPixelFormat
from ..scene.pixel_move_preview import RasterPixelMovePreview
from ..scene.source_capabilities import (
    PixelPresentationRegistry,
    PixelSampleGeometry,
)


@dataclass(frozen=True, slots=True)
class _FloatingPixelProducts:
    """Retain presentation products that do not change during pointer motion."""

    session_id: uuid.UUID
    source_asset_key: SceneLayerAssetKey
    source_patch: QImage | None
    fragment_image: QImage
    selection_mask: QImage
    product_size: QSize


class FloatingPixelRenderCompiler:
    """Adapt one immutable lift through its registered presentation owner."""

    def __init__(self, presentations: PixelPresentationRegistry) -> None:
        """Bind the sole source-presentation registry."""
        self._presentations = presentations
        self._products: _FloatingPixelProducts | None = None
        self._resolved_key: tuple[uuid.UUID, SceneLayerAssetKey, object] | None = None
        self._resolved: (
            TransientRasterResolvedContribution
            | TransientSampledResolvedContribution
            | None
        ) = None

    def compile(
        self,
        preview: RasterPixelMovePreview | None,
        render_items: tuple[SceneRenderItem, ...],
    ) -> TransientRasterContribution | None:
        """Return stable products and the current transform-only displacement."""
        if preview is None:
            self._products = None
            self._resolved_key = None
            self._resolved = None
            return None
        item = next(
            (
                candidate
                for candidate in render_items
                if candidate.descriptor.scene_id == preview.scene_id
                and candidate.descriptor.layer_id == preview.layer_id
            ),
            None,
        )
        if (
            not isinstance(
                item,
                (RasterLayerRenderItem, SampledLayerRenderItem),
            )
            or item.descriptor.raster_bounds is None
        ):
            return None
        if preview.settled_transition is not None:
            return self._compile_resolved(preview, item)
        fragment_bounds = preview.lift.fragment.bounds
        scale_x, scale_y = _item_sample_scale(item)
        product_size = QSize(
            max(1, round(fragment_bounds.width * scale_x)),
            max(1, round(fragment_bounds.height * scale_y)),
        )
        asset_key = _item_asset_key(item)
        products = self._products
        if (
            products is None
            or products.session_id != preview.session_id
            or products.source_asset_key != asset_key
            or products.product_size != product_size
        ):
            products = self._build_products(
                preview,
                item,
                asset_key,
                product_size,
            )
            self._products = products
        if products is None:
            return None
        fragment = preview.lift.fragment
        return TransientRasterTransformContribution(
            session_id=preview.session_id,
            scene_id=preview.scene_id,
            layer_id=preview.layer_id,
            source_asset_key=asset_key,
            source_patch=products.source_patch,
            source_bounds=preview.lift.source_transition.patch_bounds,
            fragment_image=products.fragment_image,
            fragment_bounds=fragment.bounds,
            selection_mask=products.selection_mask,
            fragment_transform=preview.fragment_transform,
            clear_destination=(fragment.pixel_format is RasterPixelFormat.COVERAGE8),
            extent_clip_bounds=preview.extent_clip_bounds,
        )

    @staticmethod
    def target(
        preview: RasterPixelMovePreview | None,
    ) -> tuple[uuid.UUID, uuid.UUID] | None:
        """Return the scene and layer requiring raster edit presentation."""
        if preview is None:
            return None
        return preview.scene_id, preview.layer_id

    def _compile_resolved(
        self,
        preview: RasterPixelMovePreview,
        item: RasterLayerRenderItem | SampledLayerRenderItem,
    ) -> (
        TransientRasterResolvedContribution
        | TransientSampledResolvedContribution
        | None
    ):
        """Materialize one exact settled replacement patch per release position."""
        key = (
            preview.session_id,
            _item_asset_key(item),
            preview.fragment_transform,
        )
        if key == self._resolved_key:
            return self._resolved
        transition = preview.settled_transition
        if transition is None:
            return None
        if isinstance(item, SampledLayerRenderItem):
            resolved = self._compile_sampled_resolved(preview, item)
            self._resolved_key = key
            self._resolved = resolved
            return resolved
        product_bounds = item.descriptor.raster_bounds
        if product_bounds is None:
            return None
        scale_x, scale_y = _item_sample_scale(item)
        replacement_size = QSize(
            max(1, round(transition.patch_bounds.width * scale_x)),
            max(1, round(transition.patch_bounds.height * scale_y)),
        )
        replacement = self._presentations.present_pixels(
            item.descriptor.source,
            preview.pixel_format,
            transition.after_pixels,
            replacement_size,
        )
        if replacement is None or replacement.isNull():
            return None
        resolved = TransientRasterResolvedContribution(
            session_id=preview.session_id,
            scene_id=preview.scene_id,
            layer_id=preview.layer_id,
            source_asset_key=_item_asset_key(item),
            source_image=replacement,
            source_bounds=transition.patch_bounds,
        )
        self._resolved_key = key
        self._resolved = resolved
        return resolved

    def _compile_sampled_resolved(
        self,
        preview: RasterPixelMovePreview,
        item: SampledLayerRenderItem,
    ) -> TransientSampledResolvedContribution | None:
        """Patch a settled edit into the sampled source's exact tile products."""
        transition = preview.settled_transition
        if transition is None:
            return None
        scale_x, scale_y = _item_sample_scale(item)
        sample_geometry = tuple(
            _sample_geometry(tile, scale_x, scale_y) for tile in item.tiles
        )
        exact_samples = self._presentations.present_transition_samples(
            item.descriptor.source,
            preview.pixel_format,
            transition,
            sample_geometry,
        )
        if exact_samples is not None and len(exact_samples) == len(item.tiles):
            return TransientSampledResolvedContribution(
                session_id=preview.session_id,
                scene_id=preview.scene_id,
                layer_id=preview.layer_id,
                source_asset_key=_item_asset_key(item),
                source_bounds=transition.patch_bounds,
                tiles=tuple(
                    SampledTileRenderData(
                        image,
                        tile.source_rect,
                        tile.image_source_rect,
                    )
                    for tile, image in zip(
                        item.tiles,
                        exact_samples,
                        strict=True,
                    )
                ),
            )
        replacement_size = QSize(
            max(1, round(transition.patch_bounds.width * scale_x)),
            max(1, round(transition.patch_bounds.height * scale_y)),
        )
        replacement = self._presentations.present_pixels(
            item.descriptor.source,
            preview.pixel_format,
            transition.after_pixels,
            replacement_size,
        )
        if replacement is None or replacement.isNull():
            return None
        tiles = tuple(
            _replace_sampled_tile(
                tile,
                transition.patch_bounds,
                replacement,
                scale_x,
                scale_y,
            )
            for tile in item.tiles
        )
        return TransientSampledResolvedContribution(
            session_id=preview.session_id,
            scene_id=preview.scene_id,
            layer_id=preview.layer_id,
            source_asset_key=_item_asset_key(item),
            source_bounds=transition.patch_bounds,
            tiles=tiles,
        )

    def _build_products(
        self,
        preview: RasterPixelMovePreview,
        item: RasterLayerRenderItem | SampledLayerRenderItem,
        asset_key: SceneLayerAssetKey,
        product_size: QSize,
    ) -> _FloatingPixelProducts | None:
        """Present the source remainder, fragment, and selection exactly once."""
        fragment = preview.lift.fragment
        source_patch = (
            self._presentations.present_pixels(
                item.descriptor.source,
                fragment.pixel_format,
                preview.lift.source_transition.after_pixels,
                product_size,
            )
            if preview.cut_source
            else None
        )
        if preview.cut_source and (source_patch is None or source_patch.isNull()):
            return None
        fragment_image = self._presentations.present_pixels(
            item.descriptor.source,
            fragment.pixel_format,
            fragment.materialized_pixels(),
            product_size,
        )
        if fragment_image is None or fragment_image.isNull():
            return None
        selection_mask = _alpha_mask(fragment.coverage.pixels, product_size)
        return _FloatingPixelProducts(
            session_id=preview.session_id,
            source_asset_key=asset_key,
            source_patch=source_patch,
            fragment_image=fragment_image,
            selection_mask=selection_mask,
            product_size=QSize(product_size),
        )


def _alpha_mask(coverage: np.ndarray, target_size: QSize) -> QImage:
    """Return premultiplied black whose alpha carries scalar selection coverage."""
    if int(coverage.min()) == 255:
        mask = QImage(target_size, QImage.Format_ARGB32_Premultiplied)
        mask.fill(0xFF000000)
        return mask
    sampled = qimage_to_numpy_grayscale8(
        numpy_to_qimage_grayscale8_at_size(coverage, target_size)
    )
    pixels = np.zeros((*sampled.shape, 4), dtype=np.uint8)
    pixels[:, :, 3] = sampled
    return numpy_to_qimage_argb32(pixels)


def _item_asset_key(
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


def _item_sample_scale(
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


def _replace_sampled_tile(
    tile: SampledTileRenderData,
    patch_bounds: RasterBounds,
    replacement: QImage,
    scale_x: float,
    scale_y: float,
) -> SampledTileRenderData:
    """Return one sampled tile with a settled source patch applied in place."""
    image = tile.image.copy()
    paint_origin_x = tile.source_rect.x() - tile.image_source_rect.x() / scale_x
    paint_origin_y = tile.source_rect.y() - tile.image_source_rect.y() / scale_y
    target = QRectF(
        (patch_bounds.x - paint_origin_x) * scale_x,
        (patch_bounds.y - paint_origin_y) * scale_y,
        patch_bounds.width * scale_x,
        patch_bounds.height * scale_y,
    )
    painter = QPainter(image)
    try:
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.drawImage(target, replacement, QRectF(replacement.rect()))
    finally:
        painter.end()
    return SampledTileRenderData(
        image,
        tile.source_rect,
        tile.image_source_rect,
    )


def _sample_geometry(
    tile: SampledTileRenderData,
    scale_x: float,
    scale_y: float,
) -> PixelSampleGeometry:
    """Recover one sampled tile's complete source footprint including bleed."""
    source_rect = QRectF(
        tile.source_rect.x() - tile.image_source_rect.x() / scale_x,
        tile.source_rect.y() - tile.image_source_rect.y() / scale_y,
        tile.image.width() / scale_x,
        tile.image.height() / scale_y,
    )
    return PixelSampleGeometry(source_rect, tile.image.size())
