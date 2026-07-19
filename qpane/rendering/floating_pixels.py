#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Compile exact floating raster transitions into render contributions."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QImage, QPainter, QPixmap

from ..scene.identity import SceneLayerAssetKey
from ..scene.pixel_move_preview import RasterPixelMovePreview
from ..scene.registry import LayerSourceResolverRegistry
from ..scene.render_plan import (
    FloatingPixelRenderContribution,
    MaskLayerRenderItem,
    SceneRenderItem,
    SceneRenderPlan,
)


class FloatingPixelRenderCompiler:
    """Adapt source-neutral pixel transitions through registered presentation owners."""

    def __init__(self, source_resolvers: LayerSourceResolverRegistry) -> None:
        """Bind the sole source-presentation registry."""
        self._source_resolvers = source_resolvers

    def compile(
        self,
        preview: RasterPixelMovePreview | None,
        render_items: tuple[SceneRenderItem, ...],
    ) -> FloatingPixelRenderContribution | None:
        """Return one exact replacement patch aligned to its rendered layer."""
        if preview is None:
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
        if item is None or item.descriptor.raster_bounds is None:
            return None
        image = self._source_resolvers.present_pixels(
            item.descriptor.source,
            preview.pixel_format,
            preview.transition.after_pixels,
        )
        if image is None or image.isNull():
            return None
        replacement_rect = self._replacement_rect(item, preview)
        if replacement_rect.isEmpty():
            return None
        if image.size() != replacement_rect.size():
            image = self._scaled_replacement(image, replacement_rect.size())
        source_image = (
            item.pixmap.toImage()
            if isinstance(item, MaskLayerRenderItem)
            else QImage(item.source_image)
        )
        painter = QPainter(source_image)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.drawImage(replacement_rect.topLeft(), image)
        painter.end()
        return FloatingPixelRenderContribution(
            session_id=preview.session_id,
            scene_id=preview.scene_id,
            layer_id=preview.layer_id,
            source_asset_key=item.asset_key,
            source_image=source_image,
            source_pixmap=(
                QPixmap.fromImage(source_image)
                if isinstance(item, MaskLayerRenderItem)
                else None
            ),
        )

    @staticmethod
    def _scaled_replacement(image: QImage, size: QSize) -> QImage:
        """Scale one patch through the same painter path as durable mask caches."""
        scaled = QImage(size, QImage.Format_ARGB32_Premultiplied)
        scaled.fill(0)
        painter = QPainter(scaled)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.drawImage(QRect(QPoint(0, 0), size), image, image.rect())
        painter.end()
        return scaled

    @staticmethod
    def _replacement_rect(
        item: SceneRenderItem,
        preview: RasterPixelMovePreview,
    ) -> QRect:
        """Map the canonical transition patch into render-source coordinates."""
        raster_bounds = item.descriptor.raster_bounds
        if (
            raster_bounds is None
            or raster_bounds.width <= 0
            or raster_bounds.height <= 0
        ):
            return QRect()
        render_size = (
            item.pixmap.size()
            if isinstance(item, MaskLayerRenderItem)
            else item.source_image.size()
        )
        patch = preview.transition.patch_bounds
        scale_x = render_size.width() / raster_bounds.width
        scale_y = render_size.height() / raster_bounds.height
        left = round((patch.x - raster_bounds.x) * scale_x)
        top = round((patch.y - raster_bounds.y) * scale_y)
        right = round((patch.right - raster_bounds.x) * scale_x)
        bottom = round((patch.bottom - raster_bounds.y) * scale_y)
        return QRect(left, top, right - left, bottom - top)


class FloatingPixelRenderHandoff:
    """Keep exact transient pixels visible until durable presentation catches up."""

    def __init__(self) -> None:
        """Initialize without a contribution awaiting durable presentation."""
        self._pending: FloatingPixelRenderContribution | None = None
        self._durable_asset_key: SceneLayerAssetKey | None = None

    def settled_plan(
        self,
        plan: SceneRenderPlan,
    ) -> tuple[SceneRenderPlan, bool]:
        """Return a plan that cannot flash between preview and durable revisions."""
        if plan.floating_pixels is not None:
            self._pending = plan.floating_pixels
            self._durable_asset_key = None
            return plan, False
        pending = self._pending
        if pending is None:
            return plan, False
        item = next(
            (
                candidate
                for candidate in plan.render_items
                if candidate.descriptor.scene_id == pending.scene_id
                and candidate.descriptor.layer_id == pending.layer_id
            ),
            None,
        )
        if item is None or item.asset_key == pending.source_asset_key:
            self._clear()
            return plan, True
        if self._durable_asset_key is None:
            self._durable_asset_key = item.asset_key
        elif item.asset_key != self._durable_asset_key:
            self._clear()
            return plan, True
        durable = (
            item.pixmap.toImage()
            if isinstance(item, MaskLayerRenderItem)
            else item.source_image
        )
        if durable == pending.source_image:
            self._clear()
            return plan, True
        return replace(plan, floating_pixels=pending), False

    def _clear(self) -> None:
        """Release retained transient pixels and revision identity."""
        self._pending = None
        self._durable_asset_key = None
