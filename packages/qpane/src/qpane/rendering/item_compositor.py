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
"""Composite ordered scene primitives without owning frame-buffer lifecycle."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, QSizeF, Qt
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QPen,
)

from ..scene.render_plan import (
    RasterLayerRenderItem,
    RenderStrategy,
    SampledLayerRenderItem,
    SampledTileRenderData,
    SceneRenderItem,
    SceneRenderPlan,
    TransientRasterContribution,
    TransientRasterResolvedContribution,
    TransientRasterTransformContribution,
    TransientSampledResolvedContribution,
    VectorLayerRenderItem,
)
from .layer_clip_projection import source_clip_path
from .layer_isolation import LayerIsolationCompositor
from .presentation_effect_compositor import LayerPresentationEffectCompositor
from .raster_sampling import device_aligned_raster_transform
from .tile_compositing import fallback_output_region, tile_output_rect
from .transient_raster_compositor import TransientRasterCompositor


class SceneItemCompositor:
    """Own primitive dispatch, clipping, effects, and transient layer isolation."""

    def __init__(self) -> None:
        """Initialize without a reusable transient isolation surface."""
        self._isolation = LayerIsolationCompositor()
        self._presentation_effects = LayerPresentationEffectCompositor()
        self._transient_rasters = TransientRasterCompositor(self._isolation)

    def draw_visible_items(
        self,
        painter: QPainter,
        plan: SceneRenderPlan,
        *,
        panel_clips: tuple[QRectF, ...] | None = None,
    ) -> None:
        """Draw visible scene items in bottom-to-top order."""
        self.draw_layer_items(
            painter,
            plan,
            plan.render_items,
            panel_clips=panel_clips,
        )
        self._presentation_effects.draw(
            painter,
            plan,
            draw_layer_items=self.draw_layer_items,
            item_bounds=self.item_panel_bounds,
        )

    def draw_layer_items(
        self,
        painter: QPainter,
        plan: SceneRenderPlan,
        items: tuple[SceneRenderItem, ...],
        *,
        panel_clips: tuple[QRectF, ...] | None = None,
    ) -> None:
        """Draw one ordered subset through the same source-neutral layer path."""
        index = 0
        while index < len(items):
            item = items[index]
            if not item.descriptor.visible:
                index += 1
                continue
            preview = self._transient_raster_contribution(plan, item)
            if isinstance(item, RasterLayerRenderItem) and preview is not None:
                group_end = index + 1
                while (
                    group_end < len(items)
                    and isinstance(items[group_end], RasterLayerRenderItem)
                    and items[group_end].descriptor.layer_id == item.descriptor.layer_id
                ):
                    group_end += 1
                group = tuple(
                    candidate
                    for candidate in items[index:group_end]
                    if isinstance(candidate, RasterLayerRenderItem)
                    and candidate.descriptor.visible
                )
                painter.save()
                try:
                    self._transient_rasters.draw_layer_group(
                        painter,
                        plan,
                        group,
                        preview,
                        prepare_item=self._prepare_raster_item,
                        draw_source=self.draw_raster_source,
                    )
                finally:
                    painter.restore()
                index = group_end
                continue
            painter.save()
            try:
                self.draw_item(
                    painter,
                    plan,
                    item,
                    panel_clips=panel_clips,
                )
            finally:
                painter.restore()
            index += 1

    def draw_item(
        self,
        painter: QPainter,
        plan: SceneRenderPlan,
        item: SceneRenderItem,
        *,
        panel_clips: tuple[QRectF, ...] | None = None,
    ) -> None:
        """Dispatch one closed renderer primitive."""
        if isinstance(item, RasterLayerRenderItem):
            self.draw_raster_item(
                painter,
                plan,
                item,
                panel_clips=panel_clips,
            )
        elif isinstance(item, VectorLayerRenderItem):
            self.draw_vector_item(painter, plan, item)
        elif isinstance(item, SampledLayerRenderItem):
            self.draw_sampled_item(
                painter,
                plan,
                item,
                panel_clips=panel_clips,
            )

    def draw_raster_item(
        self,
        painter: QPainter,
        plan: SceneRenderPlan,
        item: RasterLayerRenderItem,
        *,
        panel_clips: tuple[QRectF, ...] | None = None,
    ) -> None:
        """Draw one ordinary raster, isolating a transient pixel edit when active."""
        preview = self._transient_raster_contribution(plan, item)
        if isinstance(preview, TransientRasterResolvedContribution):
            if item.render_hint_enabled:
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.setOpacity(item.descriptor.opacity)
            self.apply_raster_transform(painter, item)
            self._apply_layer_clip(painter, plan, item)
            self._apply_layer_effects(painter, item)
            painter.drawImage(
                self._transient_rasters.product_rect(item, preview.source_bounds),
                preview.source_image,
                QRectF(preview.source_image.rect()),
            )
            return
        if isinstance(preview, TransientRasterTransformContribution):
            self._transient_rasters.draw_isolated_item(
                painter,
                plan,
                item,
                preview,
                draw_source=lambda target: self.draw_raster_source(
                    target,
                    plan,
                    item,
                ),
                prepare_item=self._prepare_raster_item,
            )
            return
        if item.render_hint_enabled:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setOpacity(item.descriptor.opacity)
        self.apply_raster_transform(painter, item)
        self._apply_layer_clip(painter, plan, item)
        self._apply_layer_effects(painter, item)
        self.draw_raster_source(
            painter,
            plan,
            item,
            panel_clips=panel_clips,
        )

    def draw_vector_item(
        self,
        painter: QPainter,
        plan: SceneRenderPlan,
        item: VectorLayerRenderItem,
    ) -> None:
        """Draw one semantic vector through immediate or refined products."""
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setTransform(item.transform, True)
        self._apply_layer_clip(painter, plan, item)
        self._apply_layer_effects(painter, item)
        painter.setOpacity(item.descriptor.opacity)
        if item.refined_tiles:
            if item.render_hint_enabled:
                painter.setRenderHint(
                    QPainter.RenderHint.SmoothPixmapTransform,
                    True,
                )
            for tile in item.refined_tiles:
                painter.drawImage(tile.source_rect, tile.image, tile.image_source_rect)
        elif not item.picture.isNull():
            painter.drawPicture(0, 0, item.picture)
        if item.preview_picture is not None and not item.preview_picture.isNull():
            painter.drawPicture(0, 0, item.preview_picture)
        if item.trailing_picture is not None and not item.trailing_picture.isNull():
            painter.drawPicture(0, 0, item.trailing_picture)

    def draw_sampled_item(
        self,
        painter: QPainter,
        plan: SceneRenderPlan,
        item: SampledLayerRenderItem,
        *,
        panel_clips: tuple[QRectF, ...] | None = None,
    ) -> None:
        """Draw one atomic batch of resolution-dependent sampled tiles."""
        preview = self._transient_raster_contribution(plan, item)
        if isinstance(preview, TransientSampledResolvedContribution):
            self._draw_sampled_replacement(painter, plan, item, preview)
            return
        if isinstance(preview, TransientRasterResolvedContribution):
            self._draw_resolved_sampled_item(painter, plan, item, preview)
            return
        if preview is not None:
            self._draw_isolated_sampled_item(painter, plan, item, preview)
            return
        if item.render_hint_enabled:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.apply_raster_transform(painter, item)
        self._apply_layer_clip(painter, plan, item)
        self._apply_layer_effects(painter, item)
        painter.setOpacity(item.descriptor.opacity)
        self._draw_sampled_source(
            painter,
            item,
            source_clips=self._source_clips(item, panel_clips),
        )

    @staticmethod
    def _draw_sampled_source(
        painter: QPainter,
        item: SampledLayerRenderItem,
        *,
        source_clips: tuple[QRectF, ...] | None = None,
    ) -> None:
        """Draw one sampled product batch after its layer transform is active."""
        for tile in item.tiles:
            if source_clips is not None and not any(
                tile.source_rect.intersects(source_clip) for source_clip in source_clips
            ):
                continue
            SceneItemCompositor._draw_sampled_tile(painter, tile)

    @staticmethod
    def _draw_sampled_tile(
        painter: QPainter,
        tile: SampledTileRenderData,
    ) -> None:
        """Draw one sample with optional source-local core clipping."""
        source_clip_rect = tile.source_clip_rect
        if source_clip_rect is None:
            SceneItemCompositor._draw_sampled_image(painter, tile)
            return
        painter.save()
        try:
            painter.setClipRect(source_clip_rect, Qt.ClipOperation.IntersectClip)
            SceneItemCompositor._draw_sampled_image(painter, tile)
        finally:
            painter.restore()

    @staticmethod
    def _draw_sampled_image(
        painter: QPainter,
        tile: SampledTileRenderData,
    ) -> None:
        """Preserve native sample phase while scaling derived products as needed."""
        if tile.integer_origin_sampling:
            painter.drawImage(
                round(tile.source_rect.x()),
                round(tile.source_rect.y()),
                tile.image,
            )
            return
        painter.drawImage(tile.source_rect, tile.image, tile.image_source_rect)

    def _draw_sampled_replacement(
        self,
        painter: QPainter,
        plan: SceneRenderPlan,
        item: SampledLayerRenderItem,
        preview: TransientSampledResolvedContribution,
    ) -> None:
        """Draw a settled edit through the sampled source's native tile batch."""

        def paint_layer(layer_painter: QPainter) -> None:
            """Replace overlapping sampled products on one transparent surface."""
            if item.render_hint_enabled:
                layer_painter.setRenderHint(
                    QPainter.RenderHint.SmoothPixmapTransform,
                    True,
                )
            self.apply_raster_transform(layer_painter, item)
            self._apply_layer_clip(layer_painter, plan, item)
            self._apply_layer_effects(layer_painter, item)
            layer_painter.setCompositionMode(QPainter.CompositionMode_Source)
            for tile in preview.tiles:
                self._draw_sampled_tile(layer_painter, tile)

        self._isolation.composite(
            painter,
            opacity=item.descriptor.opacity,
            paint_layer=paint_layer,
        )

    def _draw_resolved_sampled_item(
        self,
        painter: QPainter,
        plan: SceneRenderPlan,
        item: SampledLayerRenderItem,
        preview: TransientRasterResolvedContribution,
    ) -> None:
        """Replace one sampled source patch before final layer compositing."""
        if item.render_hint_enabled:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.apply_raster_transform(painter, item)
        self._apply_layer_clip(painter, plan, item)
        self._apply_layer_effects(painter, item)
        painter.setOpacity(item.descriptor.opacity)
        replacement_rect = self._transient_rasters.product_rect(
            item,
            preview.source_bounds,
        )
        source_rect = QRectF(
            0.0,
            0.0,
            float(item.source_size.width()),
            float(item.source_size.height()),
        )
        remainder = QPainterPath()
        remainder.setFillRule(Qt.FillRule.OddEvenFill)
        remainder.addRect(source_rect)
        remainder.addRect(replacement_rect)
        painter.save()
        try:
            painter.setClipPath(remainder, Qt.ClipOperation.IntersectClip)
            self._draw_sampled_source(painter, item)
        finally:
            painter.restore()
        painter.drawImage(
            replacement_rect,
            preview.source_image,
            QRectF(preview.source_image.rect()),
        )

    def _draw_isolated_sampled_item(
        self,
        painter: QPainter,
        plan: SceneRenderPlan,
        item: SampledLayerRenderItem,
        preview: TransientRasterContribution,
    ) -> None:
        """Apply a raster edit over sampled source products as one layer."""

        def paint_layer(layer_painter: QPainter) -> None:
            """Render the sampled source and active edit on an isolated surface."""
            if item.render_hint_enabled:
                layer_painter.setRenderHint(
                    QPainter.RenderHint.SmoothPixmapTransform,
                    True,
                )
            self.apply_raster_transform(layer_painter, item)
            self._apply_layer_clip(layer_painter, plan, item)
            self._apply_layer_effects(layer_painter, item)
            self._draw_sampled_source(layer_painter, item)
            if isinstance(preview, TransientRasterTransformContribution):
                if preview.extent_clip_bounds is not None:
                    layer_painter.setClipRect(
                        self._transient_rasters.product_rect(
                            item,
                            preview.extent_clip_bounds,
                        ),
                        Qt.ClipOperation.IntersectClip,
                    )
                self._transient_rasters.apply(layer_painter, item, preview)
            else:
                layer_painter.setCompositionMode(QPainter.CompositionMode_Source)
                layer_painter.drawImage(
                    self._transient_rasters.product_rect(
                        item,
                        preview.source_bounds,
                    ),
                    preview.source_image,
                )

        self._isolation.composite(
            painter,
            opacity=item.descriptor.opacity,
            paint_layer=paint_layer,
        )

    @staticmethod
    def apply_raster_transform(
        painter: QPainter,
        item: RasterLayerRenderItem | SampledLayerRenderItem,
    ) -> None:
        """Apply one stable device-pixel phase across complete and repaired frames."""
        painter.setTransform(item.transform, True)
        painter.setWorldTransform(
            device_aligned_raster_transform(
                painter.worldTransform(),
                float(painter.device().devicePixelRatioF()),
            ),
            False,
        )

    def _prepare_raster_item(
        self,
        painter: QPainter,
        plan: SceneRenderPlan,
        item: RasterLayerRenderItem | SampledLayerRenderItem,
    ) -> None:
        """Apply shared raster sampling, geometry, clipping, and effects."""
        if item.render_hint_enabled:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.apply_raster_transform(painter, item)
        self._apply_layer_clip(painter, plan, item)
        self._apply_layer_effects(painter, item)

    def draw_raster_source(
        self,
        painter: QPainter,
        plan: SceneRenderPlan,
        item: RasterLayerRenderItem,
        *,
        panel_clips: tuple[QRectF, ...] | None = None,
    ) -> None:
        """Draw one raster source through its selected strategy."""
        if item.strategy == RenderStrategy.DIRECT:
            self._draw_direct_view(painter, item)
        elif item.strategy == RenderStrategy.TILE:
            self._draw_tiled_view(
                painter,
                plan,
                item,
                source_clips=self._source_clips(item, panel_clips),
            )

    @staticmethod
    def _source_clips(
        item: SceneRenderItem,
        panel_clips: tuple[QRectF, ...] | None,
    ) -> tuple[QRectF, ...] | None:
        """Map optional panel repair clips into one item's source space."""
        if panel_clips is None:
            return None
        inverse, invertible = item.transform.inverted()
        if not invertible:
            return ()
        return tuple(inverse.mapRect(panel_clip) for panel_clip in panel_clips)

    @staticmethod
    def _draw_direct_view(painter: QPainter, item: RasterLayerRenderItem) -> None:
        """Draw the direct source product."""
        painter.drawImage(0, 0, item.source_image)

    @staticmethod
    def item_panel_bounds(item: SceneRenderItem) -> QRect:
        """Return conservative panel bounds for one primitive."""
        source_width, source_height = SceneItemCompositor.item_source_size(item)
        if source_width <= 0 or source_height <= 0:
            return QRect()
        source_rect = (
            QRectF(item.source_bounds)
            if isinstance(item, SampledLayerRenderItem)
            and item.source_bounds is not None
            else QRectF(0.0, 0.0, float(source_width), float(source_height))
        )
        return (
            item.transform.mapRect(source_rect).toAlignedRect().adjusted(-1, -1, 1, 1)
        )

    @staticmethod
    def item_source_size(item: SceneRenderItem) -> tuple[int, int]:
        """Return source dimensions for one primitive."""
        if isinstance(item, RasterLayerRenderItem):
            return item.source_image.width(), item.source_image.height()
        if isinstance(item, SampledLayerRenderItem):
            return item.source_size.width(), item.source_size.height()
        return item.source_size.width(), item.source_size.height()

    @staticmethod
    def _transient_raster_contribution(
        plan: SceneRenderPlan,
        item: RasterLayerRenderItem,
    ) -> TransientRasterContribution | None:
        """Return the contribution when this item owns it."""
        preview = plan.transient_raster
        if (
            preview is None
            or preview.scene_id != plan.scene_id
            or preview.layer_id != item.descriptor.layer_id
        ):
            return None
        return preview

    def _apply_layer_clip(
        self,
        painter: QPainter,
        plan: SceneRenderPlan,
        item: SceneRenderItem,
    ) -> None:
        """Intersect one layer clip without broadening ambient frame damage."""
        path = source_clip_path(plan, item)
        if path is not None:
            painter.setClipPath(path, Qt.ClipOperation.IntersectClip)

    @staticmethod
    def _apply_layer_effects(painter: QPainter, item: SceneRenderItem) -> None:
        """Intersect one primitive with its compiled target-local effects."""
        if item.effect_clip_path is not None:
            painter.setClipPath(
                item.effect_clip_path,
                Qt.ClipOperation.IntersectClip,
            )

    def _draw_tiled_view(
        self,
        painter: QPainter,
        plan: SceneRenderPlan,
        item: RasterLayerRenderItem,
        *,
        source_clips: tuple[QRectF, ...] | None = None,
    ) -> None:
        """Draw visible source tiles with the direct product as a fallback."""
        source_rect = item.source_image.rect()
        image_rect = QRectF(source_rect)
        tile_rects = tuple(
            tile_output_rect(tile, source_rect, item.tile_overlap)
            for tile in item.tiles_to_draw
        )
        painter.save()
        painter.setClipRect(
            image_rect.adjusted(-0.5, -0.5, 0.5, 0.5),
            Qt.ClipOperation.IntersectClip,
        )
        if tile_rects:
            painter.save()
            painter.setClipRegion(
                fallback_output_region(source_rect, tile_rects),
                Qt.ClipOperation.IntersectClip,
            )
            painter.drawImage(0, 0, item.source_image)
            painter.restore()
        else:
            painter.drawImage(0, 0, item.source_image)
        for tile, tile_rect in zip(item.tiles_to_draw, tile_rects, strict=True):
            if tile_rect.isEmpty() or (
                source_clips is not None
                and not any(
                    QRectF(tile_rect).intersects(source_clip)
                    for source_clip in source_clips
                )
            ):
                continue
            painter.save()
            painter.setClipRect(tile_rect, Qt.ClipOperation.IntersectClip)
            painter.drawImage(tile.draw_pos, tile.image)
            painter.restore()
        if item.debug_draw_tile_grid:
            self._draw_tile_debug_overlay(painter, plan, item)
        painter.restore()

    @staticmethod
    def _draw_tile_debug_overlay(
        painter: QPainter,
        plan: SceneRenderPlan,
        item: RasterLayerRenderItem,
    ) -> None:
        """Draw the configured diagnostic grid over visible source tiles."""
        if item.max_tile_cols <= 0 or item.max_tile_rows <= 0:
            return
        visible_range = item.visible_tile_range
        if visible_range is None:
            return
        start_row, end_row, start_col, end_col = visible_range
        if start_row > end_row or start_col > end_col:
            return
        stride = max(1, item.tile_size - item.tile_overlap)
        effective_zoom = plan.zoom / item.pyramid_scale
        pen = QPen(QColor(255, 0, 0, 100))
        pen.setWidthF(2.0 / effective_zoom)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        for row in range(start_row, end_row + 1):
            for column in range(start_col, end_col + 1):
                draw_pos = QPointF(column * stride, row * stride)
                painter.drawRect(
                    QRectF(draw_pos, QSizeF(item.tile_size, item.tile_size))
                )
