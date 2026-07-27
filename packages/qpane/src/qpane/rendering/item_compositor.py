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

from collections.abc import Callable

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, QSizeF, Qt
from PySide6.QtGui import (
    QColor,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QTransform,
)

from ..scene.affine import LayerTransform
from ..scene.model import ClipCoordinateSpace
from ..scene.raster import RasterBounds
from ..scene.render_plan import (
    RasterLayerRenderItem,
    RenderStrategy,
    SampledLayerRenderItem,
    SceneRenderItem,
    SceneRenderPlan,
    TransientRasterContribution,
    TransientRasterResolvedContribution,
    TransientRasterTransformContribution,
    TransientSampledResolvedContribution,
    VectorLayerRenderItem,
)
from .presentation_effect_compositor import LayerPresentationEffectCompositor
from .raster_sampling import device_aligned_raster_transform
from .tile_compositing import fallback_output_region, tile_output_rect


class SceneItemCompositor:
    """Own primitive dispatch, clipping, effects, and transient layer isolation."""

    def __init__(self) -> None:
        """Initialize without a reusable transient isolation surface."""
        self._isolation_buffer: QImage | None = None
        self._presentation_effects = LayerPresentationEffectCompositor()

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
                    self._draw_transient_layer_group(painter, plan, group, preview)
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
                self._product_rect(item, preview.source_bounds),
                preview.source_image,
                QRectF(preview.source_image.rect()),
            )
            return
        if isinstance(preview, TransientRasterTransformContribution):
            self._draw_isolated_transient_item(
                painter,
                plan,
                item,
                preview,
                lambda target: self.draw_raster_source(target, plan, item),
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
            painter.drawImage(tile.source_rect, tile.image, tile.image_source_rect)

    def _draw_sampled_replacement(
        self,
        painter: QPainter,
        plan: SceneRenderPlan,
        item: SampledLayerRenderItem,
        preview: TransientSampledResolvedContribution,
    ) -> None:
        """Draw a settled edit through the sampled source's native tile batch."""
        if item.render_hint_enabled:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.apply_raster_transform(painter, item)
        self._apply_layer_clip(painter, plan, item)
        self._apply_layer_effects(painter, item)
        painter.setOpacity(item.descriptor.opacity)
        for tile in preview.tiles:
            painter.drawImage(tile.source_rect, tile.image, tile.image_source_rect)

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
        replacement_rect = self._product_rect(item, preview.source_bounds)
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
        buffer = self._prepare_isolation_buffer(painter)
        layer_painter = QPainter(buffer)
        try:
            layer_painter.setWorldTransform(painter.worldTransform())
            if painter.hasClipping():
                layer_painter.setClipRegion(painter.clipRegion())
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
                        self._product_rect(item, preview.extent_clip_bounds),
                        Qt.ClipOperation.IntersectClip,
                    )
                self._apply_transient_products(layer_painter, item, preview)
            else:
                layer_painter.setCompositionMode(QPainter.CompositionMode_Source)
                layer_painter.drawImage(
                    self._product_rect(item, preview.source_bounds),
                    preview.source_image,
                )
        finally:
            layer_painter.end()
        painter.save()
        try:
            painter.resetTransform()
            painter.setOpacity(item.descriptor.opacity)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.drawImage(QPointF(), buffer)
        finally:
            painter.restore()

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

    def draw_raster_source(
        self,
        painter: QPainter,
        plan: SceneRenderPlan,
        item: RasterLayerRenderItem,
        *,
        panel_clips: tuple[QRectF, ...] | None = None,
    ) -> None:
        """Draw one raster source through its selected strategy."""
        painter.save()
        try:
            if item.source_clip_rect is not None:
                painter.setClipRect(
                    item.source_clip_rect,
                    Qt.ClipOperation.IntersectClip,
                )
            if item.strategy == RenderStrategy.DIRECT:
                self._draw_direct_view(painter, item)
            elif item.strategy == RenderStrategy.TILE:
                self._draw_tiled_view(
                    painter,
                    plan,
                    item,
                    source_clips=self._source_clips(item, panel_clips),
                )
        finally:
            painter.restore()

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
        source_rect = QRectF(0.0, 0.0, float(source_width), float(source_height))
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

    def _draw_isolated_transient_item(
        self,
        painter: QPainter,
        plan: SceneRenderPlan,
        item: RasterLayerRenderItem,
        preview: TransientRasterTransformContribution,
        draw_source: Callable[[QPainter], None],
    ) -> None:
        """Composite one edited layer independently from the accumulated backdrop."""
        buffer = self._prepare_isolation_buffer(painter)
        layer_painter = QPainter(buffer)
        try:
            layer_painter.setWorldTransform(painter.worldTransform())
            if painter.hasClipping():
                layer_painter.setClipRegion(painter.clipRegion())
            if item.render_hint_enabled:
                layer_painter.setRenderHint(
                    QPainter.RenderHint.SmoothPixmapTransform,
                    True,
                )
            self.apply_raster_transform(layer_painter, item)
            self._apply_layer_clip(layer_painter, plan, item)
            self._apply_layer_effects(layer_painter, item)
            if preview.extent_clip_bounds is not None:
                layer_painter.setClipRect(
                    self._product_rect(item, preview.extent_clip_bounds),
                    Qt.ClipOperation.IntersectClip,
                )
            draw_source(layer_painter)
            self._apply_transient_products(layer_painter, item, preview)
        finally:
            layer_painter.end()
        painter.save()
        try:
            painter.resetTransform()
            painter.setOpacity(item.descriptor.opacity)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.drawImage(QPointF(0.0, 0.0), buffer)
        finally:
            painter.restore()

    def _draw_transient_layer_group(
        self,
        painter: QPainter,
        plan: SceneRenderPlan,
        items: tuple[RasterLayerRenderItem, ...],
        preview: TransientRasterContribution,
    ) -> None:
        """Composite every sparse product for one edited layer as one surface."""
        if not items:
            return
        buffer = self._prepare_isolation_buffer(painter)
        layer_painter = QPainter(buffer)
        try:
            layer_painter.setWorldTransform(painter.worldTransform())
            if painter.hasClipping():
                layer_painter.setClipRegion(painter.clipRegion())
            for item in items:
                layer_painter.save()
                try:
                    if item.render_hint_enabled:
                        layer_painter.setRenderHint(
                            QPainter.RenderHint.SmoothPixmapTransform,
                            True,
                        )
                    self.apply_raster_transform(layer_painter, item)
                    self._apply_layer_clip(layer_painter, plan, item)
                    self._apply_layer_effects(layer_painter, item)
                    self.draw_raster_source(layer_painter, plan, item)
                finally:
                    layer_painter.restore()
            reference = items[0]
            layer_painter.save()
            try:
                if reference.render_hint_enabled:
                    layer_painter.setRenderHint(
                        QPainter.RenderHint.SmoothPixmapTransform,
                        True,
                    )
                self.apply_raster_transform(layer_painter, reference)
                self._apply_layer_clip(layer_painter, plan, reference)
                self._apply_layer_effects(layer_painter, reference)
                if isinstance(preview, TransientRasterTransformContribution):
                    if preview.extent_clip_bounds is not None:
                        layer_painter.setClipRect(
                            self._product_rect(
                                reference,
                                preview.extent_clip_bounds,
                            ),
                            Qt.ClipOperation.IntersectClip,
                        )
                    self._apply_transient_products(
                        layer_painter,
                        reference,
                        preview,
                    )
                else:
                    layer_painter.setCompositionMode(QPainter.CompositionMode_Source)
                    layer_painter.drawImage(
                        self._product_rect(reference, preview.source_bounds),
                        preview.source_image,
                    )
            finally:
                layer_painter.restore()
        finally:
            layer_painter.end()
        painter.save()
        try:
            painter.resetTransform()
            painter.setOpacity(items[0].descriptor.opacity)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.drawImage(QPointF(0.0, 0.0), buffer)
        finally:
            painter.restore()

    def _prepare_isolation_buffer(self, painter: QPainter) -> QImage:
        """Return a reusable transparent surface matching the frame buffer."""
        device = painter.device()
        size = QSize(device.width(), device.height())
        dpr = float(device.devicePixelRatioF())
        buffer = self._isolation_buffer
        if (
            buffer is None
            or buffer.size() != size
            or abs(buffer.devicePixelRatioF() - dpr) > 1e-6
        ):
            buffer = QImage(size, QImage.Format_ARGB32_Premultiplied)
            buffer.setDevicePixelRatio(dpr)
            self._isolation_buffer = buffer
            buffer.fill(Qt.transparent)
        elif painter.hasClipping():
            clear = QPainter(buffer)
            try:
                clear.setWorldTransform(painter.worldTransform())
                clear.setClipRegion(painter.clipRegion())
                clear.setCompositionMode(QPainter.CompositionMode_Source)
                clear.fillRect(painter.clipBoundingRect(), Qt.transparent)
            finally:
                clear.end()
        else:
            buffer.fill(Qt.transparent)
        return buffer

    def _apply_transient_products(
        self,
        painter: QPainter,
        item: RasterLayerRenderItem | SampledLayerRenderItem,
        preview: TransientRasterTransformContribution,
    ) -> None:
        """Apply stable source and fragment products at current local geometry."""
        if preview.source_patch is not None:
            painter.setCompositionMode(QPainter.CompositionMode_Source)
            painter.drawImage(
                self._product_rect(item, preview.source_bounds),
                preview.source_patch,
            )
        source_rect = self._product_rect(item, preview.fragment_bounds)
        painter.save()
        try:
            painter.setTransform(
                self._product_transform(item, preview.fragment_transform),
                True,
            )
            if preview.clear_destination:
                painter.setCompositionMode(QPainter.CompositionMode_DestinationOut)
                painter.drawImage(source_rect, preview.selection_mask)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.drawImage(source_rect, preview.fragment_image)
        finally:
            painter.restore()

    @staticmethod
    def _product_transform(
        item: RasterLayerRenderItem | SampledLayerRenderItem,
        transform: LayerTransform,
    ) -> QTransform:
        """Conjugate one local affine transform into display-product coordinates."""
        bounds = item.descriptor.raster_bounds
        if bounds is None:
            return QTransform()
        source_width, source_height = SceneItemCompositor.item_source_size(item)
        scale_x = source_width / bounds.width
        scale_y = source_height / bounds.height
        product_to_local = QTransform()
        product_to_local.translate(float(bounds.x), float(bounds.y))
        product_to_local.scale(1.0 / scale_x, 1.0 / scale_y)
        local_to_product = product_to_local.inverted()[0]
        return product_to_local * transform.to_qtransform() * local_to_product

    @staticmethod
    def _product_rect(
        item: RasterLayerRenderItem | SampledLayerRenderItem,
        bounds: RasterBounds,
    ) -> QRectF:
        """Map authoritative local bounds into one item's current source product."""
        raster_bounds = item.descriptor.raster_bounds
        if (
            raster_bounds is None
            or raster_bounds.width <= 0
            or raster_bounds.height <= 0
        ):
            return QRectF()
        source_width, source_height = SceneItemCompositor.item_source_size(item)
        scale_x = source_width / raster_bounds.width
        scale_y = source_height / raster_bounds.height
        return QRectF(
            (bounds.x - raster_bounds.x) * scale_x,
            (bounds.y - raster_bounds.y) * scale_y,
            bounds.width * scale_x,
            bounds.height * scale_y,
        )

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
        """Apply one layer clip in its declared coordinate space."""
        clip = item.clip
        if clip is None:
            return
        source_width, source_height = self.item_source_size(item)
        if clip.coordinate_space == ClipCoordinateSpace.NORMALIZED_SCENE:
            scene_clip = QRectF(
                plan.scene_bounds.x + clip.x * plan.scene_bounds.width,
                plan.scene_bounds.y + clip.y * plan.scene_bounds.height,
                clip.width * plan.scene_bounds.width,
                clip.height * plan.scene_bounds.height,
            )
        elif clip.coordinate_space == ClipCoordinateSpace.SCENE:
            scene_clip = QRectF(clip.x, clip.y, clip.width, clip.height)
        elif clip.coordinate_space == ClipCoordinateSpace.NORMALIZED_VIEWPORT:
            viewport_clip = QRectF(
                plan.qpane_rect.x() + clip.x * plan.qpane_rect.width(),
                plan.qpane_rect.y() + clip.y * plan.qpane_rect.height(),
                clip.width * plan.qpane_rect.width(),
                clip.height * plan.qpane_rect.height(),
            )
            painter.setClipRect(self._viewport_clip_to_source(item, viewport_clip))
            return
        elif clip.coordinate_space == ClipCoordinateSpace.VIEWPORT:
            painter.setClipRect(
                self._viewport_clip_to_source(
                    item,
                    QRectF(clip.x, clip.y, clip.width, clip.height),
                )
            )
            return
        else:
            return
        painter.setClipRect(
            self._scene_clip_to_source(
                item,
                scene_clip,
                source_width=source_width,
                source_height=source_height,
            )
        )

    @staticmethod
    def _apply_layer_effects(painter: QPainter, item: SceneRenderItem) -> None:
        """Intersect one primitive with its compiled target-local effects."""
        if item.effect_clip_path is not None:
            painter.setClipPath(
                item.effect_clip_path,
                Qt.ClipOperation.IntersectClip,
            )

    @staticmethod
    def _scene_clip_to_source(
        item: SceneRenderItem,
        scene_clip: QRectF,
        *,
        source_width: int,
        source_height: int,
    ) -> QRectF:
        """Convert a scene-space clip into primitive source coordinates."""
        placement = item.placement
        if placement.width <= 0.0 or placement.height <= 0.0:
            return QRectF()
        return QRectF(
            (scene_clip.x() - placement.x) * source_width / placement.width,
            (scene_clip.y() - placement.y) * source_height / placement.height,
            scene_clip.width() * source_width / placement.width,
            scene_clip.height() * source_height / placement.height,
        )

    @staticmethod
    def _viewport_clip_to_source(
        item: SceneRenderItem,
        viewport_clip: QRectF,
    ) -> QRectF:
        """Convert a viewport-space clip into primitive source coordinates."""
        inverse, invertible = item.transform.inverted()
        return inverse.mapRect(viewport_clip) if invertible else QRectF()

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
