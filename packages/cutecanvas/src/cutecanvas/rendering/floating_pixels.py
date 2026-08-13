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
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
from qpane.sdk.raster import (
    numpy_to_qimage_argb32,
)
from qpane.sdk.scene import (
    RasterBounds,
    RasterLayerRenderItem,
    SampledLayerRenderItem,
    SceneLayerAssetKey,
    SceneRenderItem,
    TransientRasterContribution,
    TransientRasterResolvedContribution,
    TransientRasterTransformContribution,
    TransientSampledResolvedContribution,
)

from ..raster.preview_sampling import sample_coverage_preview
from ..scene.pixel_fragments import RasterPixelFormat
from ..scene.pixel_move_preview import RasterPixelMovePreview
from ..scene.pixel_transitions import RasterPixelTransition
from ..scene.source_capabilities import (
    PixelPresentationRegistry,
)
from .raster_transitions import (
    RasterTransitionRenderCompiler,
    raster_item_asset_key,
    raster_item_sample_scale,
)


@dataclass(frozen=True, slots=True)
class _FloatingPixelProducts:
    """Retain presentation products that do not change during pointer motion."""

    session_id: uuid.UUID
    source_asset_key: SceneLayerAssetKey
    source_patch: QImage | None
    fragment_image: QImage
    destination_attenuation_mask: QImage | None
    product_size: QSize


class FloatingPixelRenderCompiler:
    """Adapt one immutable lift through its registered presentation owner."""

    def __init__(self, presentations: PixelPresentationRegistry) -> None:
        """Bind the sole source-presentation registry."""
        self._presentations = presentations
        self._transition_compiler = RasterTransitionRenderCompiler(presentations)
        self._products: _FloatingPixelProducts | None = None

    def compile(
        self,
        preview: RasterPixelMovePreview | None,
        render_items: tuple[SceneRenderItem, ...],
    ) -> TransientRasterContribution | None:
        """Return stable products and the current transform-only displacement."""
        if preview is None:
            self._products = None
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
        scale_x, scale_y = raster_item_sample_scale(item)
        product_size = QSize(
            max(1, round(fragment_bounds.width * scale_x)),
            max(1, round(fragment_bounds.height * scale_y)),
        )
        asset_key = raster_item_asset_key(item)
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
            destination_attenuation_mask=(products.destination_attenuation_mask),
            fragment_transform=preview.fragment_transform,
            extent_clip_bounds=preview.extent_clip_bounds,
        )

    @staticmethod
    def target(
        preview: RasterPixelMovePreview | None,
    ) -> tuple[uuid.UUID, uuid.UUID, RasterBounds] | None:
        """Return the target and local bounds requiring raster presentation."""
        if preview is None:
            return None
        support_bounds = (
            preview.lift.source_transition.patch_bounds
            if preview.settled_transition is None
            else preview.settled_transition.patch_bounds
        )
        return (
            preview.scene_id,
            preview.layer_id,
            support_bounds,
        )

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
        transition = preview.settled_transition
        if transition is None:
            return None
        return self.compile_resolved_transition(
            session_id=preview.session_id,
            scene_id=preview.scene_id,
            layer_id=preview.layer_id,
            pixel_format=preview.pixel_format,
            transition=transition,
            generation=preview.fragment_transform,
            item=item,
        )

    def compile_resolved_transition(
        self,
        *,
        session_id: uuid.UUID,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        pixel_format: RasterPixelFormat,
        transition: RasterPixelTransition,
        generation: object,
        item: RasterLayerRenderItem | SampledLayerRenderItem,
    ) -> (
        TransientRasterResolvedContribution
        | TransientSampledResolvedContribution
        | None
    ):
        """Present one exact transition through an existing raster render item."""
        return self._transition_compiler.compile(
            session_id=session_id,
            scene_id=scene_id,
            layer_id=layer_id,
            pixel_format=pixel_format,
            transition=transition,
            generation=generation,
            item=item,
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
        destination_attenuation_mask = (
            _alpha_mask(
                fragment.contribution_coverage.pixels,
                product_size,
            )
            if fragment.pixel_format is RasterPixelFormat.COVERAGE8
            else None
        )
        return _FloatingPixelProducts(
            session_id=preview.session_id,
            source_asset_key=asset_key,
            source_patch=source_patch,
            fragment_image=fragment_image,
            destination_attenuation_mask=destination_attenuation_mask,
            product_size=QSize(product_size),
        )


def _alpha_mask(coverage: np.ndarray, target_size: QSize) -> QImage:
    """Return premultiplied black whose alpha carries scalar selection coverage."""
    if int(coverage.min()) == 255:
        mask = QImage(target_size, QImage.Format_ARGB32_Premultiplied)
        mask.fill(0xFF000000)
        return mask
    sampled = sample_coverage_preview(coverage, target_size)
    pixels = np.zeros((*sampled.shape, 4), dtype=np.uint8)
    pixels[:, :, 3] = sampled
    return numpy_to_qimage_argb32(pixels)
