#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Compile stable lifted-pixel products for transient scene composition."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace

import numpy as np
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage

from ..raster.image_conversion import (
    numpy_to_qimage_argb32,
    numpy_to_qimage_grayscale8_at_size,
    qimage_to_numpy_grayscale8,
)
from ..scene.identity import SceneLayerAssetKey
from ..scene.pixel_fragments import RasterPixelFormat
from ..scene.pixel_move_preview import RasterPixelMovePreview
from ..scene.render_plan import (
    FloatingPixelRenderContribution,
    FloatingPixelResolvedContribution,
    FloatingPixelTransformContribution,
    RasterLayerRenderItem,
    SceneRenderItem,
    SceneRenderPlan,
)
from ..scene.source_capabilities import PixelPresentationRegistry


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
        self._resolved: FloatingPixelResolvedContribution | None = None

    def compile(
        self,
        preview: RasterPixelMovePreview | None,
        render_items: tuple[SceneRenderItem, ...],
    ) -> FloatingPixelRenderContribution | None:
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
            not isinstance(item, RasterLayerRenderItem)
            or item.descriptor.raster_bounds is None
        ):
            return None
        if preview.settled_transition is not None:
            return self._compile_resolved(preview, item)
        fragment_bounds = preview.lift.fragment.bounds
        product_size = QSize(
            max(1, round(fragment_bounds.width * item.pyramid_scale)),
            max(1, round(fragment_bounds.height * item.pyramid_scale)),
        )
        products = self._products
        if (
            products is None
            or products.session_id != preview.session_id
            or products.source_asset_key != item.asset_key
            or products.product_size != product_size
        ):
            products = self._build_products(preview, item, product_size)
            self._products = products
        if products is None:
            return None
        fragment = preview.lift.fragment
        return FloatingPixelTransformContribution(
            session_id=preview.session_id,
            scene_id=preview.scene_id,
            layer_id=preview.layer_id,
            source_asset_key=item.asset_key,
            source_patch=products.source_patch,
            source_bounds=preview.lift.source_transition.patch_bounds,
            fragment_image=products.fragment_image,
            fragment_bounds=fragment.bounds,
            selection_mask=products.selection_mask,
            fragment_transform=preview.fragment_transform,
            clear_destination=(fragment.pixel_format is RasterPixelFormat.COVERAGE8),
            extent_clip_bounds=preview.extent_clip_bounds,
        )

    def _compile_resolved(
        self,
        preview: RasterPixelMovePreview,
        item: RasterLayerRenderItem,
    ) -> FloatingPixelResolvedContribution | None:
        """Materialize one exact settled replacement patch per release position."""
        key = (
            preview.session_id,
            item.asset_key,
            preview.fragment_transform,
        )
        if key == self._resolved_key:
            return self._resolved
        transition = preview.settled_transition
        if transition is None:
            return None
        product_bounds = item.descriptor.raster_bounds
        if product_bounds is None:
            return None
        scale_x = item.source_image.width() / product_bounds.width
        scale_y = item.source_image.height() / product_bounds.height
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
        resolved = FloatingPixelResolvedContribution(
            session_id=preview.session_id,
            scene_id=preview.scene_id,
            layer_id=preview.layer_id,
            source_asset_key=item.asset_key,
            source_image=replacement,
            source_bounds=transition.patch_bounds,
        )
        self._resolved_key = key
        self._resolved = resolved
        return resolved

    def _build_products(
        self,
        preview: RasterPixelMovePreview,
        item: RasterLayerRenderItem,
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
            source_asset_key=item.asset_key,
            source_patch=source_patch,
            fragment_image=fragment_image,
            selection_mask=selection_mask,
            product_size=QSize(product_size),
        )


class FloatingPixelRenderHandoff:
    """Keep transient pixels visible until the durable revision is presented."""

    def __init__(self) -> None:
        """Initialize without a contribution awaiting durable presentation."""
        self._pending: FloatingPixelRenderContribution | None = None
        self._durable_asset_key: SceneLayerAssetKey | None = None

    def settled_plan(
        self,
        plan: SceneRenderPlan,
    ) -> tuple[SceneRenderPlan, bool]:
        """Return a plan that cannot flash before a newer durable revision arrives."""
        if plan.floating_pixels is not None:
            self._pending = plan.floating_pixels
            self._durable_asset_key = None
            return plan, False
        pending = self._pending
        if pending is None:
            return plan, False
        if isinstance(pending, FloatingPixelTransformContribution):
            self._clear()
            return plan, True
        item = next(
            (
                candidate
                for candidate in plan.render_items
                if candidate.descriptor.scene_id == pending.scene_id
                and candidate.descriptor.layer_id == pending.layer_id
            ),
            None,
        )
        if not isinstance(item, RasterLayerRenderItem):
            self._clear()
            return plan, True
        if item.asset_key == pending.source_asset_key:
            return replace(plan, floating_pixels=pending), False
        if self._durable_asset_key is None:
            self._durable_asset_key = item.asset_key
        elif item.asset_key != self._durable_asset_key:
            self._clear()
            return plan, True
        if item.source_image == pending.source_image:
            self._clear()
            return plan, True
        return replace(plan, floating_pixels=pending), False

    def _clear(self) -> None:
        """Release retained transient products and revision identity."""
        self._pending = None
        self._durable_asset_key = None


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
