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

"""Composite sampled sources and their exact transient replacements."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath

from ..scene.render_plan import (
    SampledLayerRenderItem,
    SampledTileRenderData,
    SceneRenderItem,
    SceneRenderPlan,
    TransientRasterContribution,
    TransientRasterResolvedContribution,
    TransientRasterTransformContribution,
    TransientSampledResolvedContribution,
)
from .layer_isolation import LayerIsolationCompositor
from .transient_raster_compositor import TransientRasterCompositor

_ApplyTransform = Callable[[QPainter, SampledLayerRenderItem], None]
_ApplyClip = Callable[[QPainter, SceneRenderPlan, SceneRenderItem], None]
_ApplyEffects = Callable[[QPainter, SceneRenderItem], None]


class SampledItemCompositor:
    """Own sampled product drawing and transient replacement settlement."""

    def __init__(
        self,
        isolation: LayerIsolationCompositor,
        transient_rasters: TransientRasterCompositor,
        *,
        apply_transform: _ApplyTransform,
        apply_clip: _ApplyClip,
        apply_effects: _ApplyEffects,
    ) -> None:
        """Bind shared layer presentation collaborators."""
        self._isolation = isolation
        self._transient_rasters = transient_rasters
        self._apply_transform = apply_transform
        self._apply_clip = apply_clip
        self._apply_effects = apply_effects

    def draw(
        self,
        painter: QPainter,
        plan: SceneRenderPlan,
        item: SampledLayerRenderItem,
        preview: TransientRasterContribution | None,
        *,
        panel_clips: tuple[QRectF, ...] | None,
    ) -> None:
        """Draw one atomic batch and any exact in-flight replacement."""
        if isinstance(preview, TransientSampledResolvedContribution):
            self._draw_sampled_replacement(painter, plan, item, preview)
            return
        if isinstance(preview, TransientRasterResolvedContribution):
            self._draw_resolved_replacement(painter, plan, item, preview)
            return
        if preview is not None:
            self._draw_isolated_replacement(painter, plan, item, preview)
            return
        self._prepare_item(painter, plan, item)
        painter.setOpacity(item.descriptor.opacity)
        self._draw_source(
            painter,
            item,
            source_clips=_source_clips(item, panel_clips),
        )

    def _prepare_item(
        self,
        painter: QPainter,
        plan: SceneRenderPlan,
        item: SampledLayerRenderItem,
    ) -> None:
        """Apply sampling, mapping, clipping, and effects for one sampled layer."""
        if item.render_hint_enabled:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self._apply_transform(painter, item)
        self._apply_clip(painter, plan, item)
        self._apply_effects(painter, item)

    def _draw_sampled_replacement(
        self,
        painter: QPainter,
        plan: SceneRenderPlan,
        item: SampledLayerRenderItem,
        preview: TransientSampledResolvedContribution,
    ) -> None:
        """Draw a settled edit through the source's native sample batch."""
        self._prepare_item(painter, plan, item)
        painter.setOpacity(item.descriptor.opacity)
        self._draw_tiles(painter, preview.tiles)

    def _draw_resolved_replacement(
        self,
        painter: QPainter,
        plan: SceneRenderPlan,
        item: SampledLayerRenderItem,
        preview: TransientRasterResolvedContribution,
    ) -> None:
        """Replace one sampled source patch before final layer compositing."""
        self._prepare_item(painter, plan, item)
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
            self._draw_source(painter, item)
        finally:
            painter.restore()
        painter.drawImage(
            replacement_rect,
            preview.source_image,
            QRectF(preview.source_image.rect()),
        )

    def _draw_isolated_replacement(
        self,
        painter: QPainter,
        plan: SceneRenderPlan,
        item: SampledLayerRenderItem,
        preview: TransientRasterContribution,
    ) -> None:
        """Apply one raster edit over sampled products as an atomic layer."""

        def paint_layer(layer_painter: QPainter) -> None:
            """Render the sampled source and active edit on one surface."""
            self._prepare_item(layer_painter, plan, item)
            self._draw_source(layer_painter, item)
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
                return
            layer_painter.setCompositionMode(QPainter.CompositionMode_Source)
            layer_painter.drawImage(
                self._transient_rasters.product_rect(item, preview.source_bounds),
                preview.source_image,
            )

        self._isolation.composite(
            painter,
            opacity=item.descriptor.opacity,
            paint_layer=paint_layer,
        )

    @staticmethod
    def _draw_source(
        painter: QPainter,
        item: SampledLayerRenderItem,
        *,
        source_clips: tuple[QRectF, ...] | None = None,
    ) -> None:
        """Draw one sampled batch after its layer transform is active."""
        SampledItemCompositor._draw_tiles(
            painter,
            item.tiles,
            source_clips=source_clips,
        )

    @staticmethod
    def _draw_tiles(
        painter: QPainter,
        tiles: tuple[SampledTileRenderData, ...],
        *,
        source_clips: tuple[QRectF, ...] | None = None,
    ) -> None:
        """Draw one atomic sampled batch through the current layer state."""
        for tile in tiles:
            if source_clips is not None and not any(
                tile.source_rect.intersects(source_clip) for source_clip in source_clips
            ):
                continue
            _draw_sampled_tile(painter, tile)


def _draw_sampled_tile(painter: QPainter, tile: SampledTileRenderData) -> None:
    """Draw one sample with optional source-local core clipping."""
    source_clip_rect = tile.source_clip_rect
    if source_clip_rect is None:
        _draw_sampled_image(painter, tile)
        return
    painter.save()
    try:
        painter.setClipRect(source_clip_rect, Qt.ClipOperation.IntersectClip)
        _draw_sampled_image(painter, tile)
    finally:
        painter.restore()


def _draw_sampled_image(painter: QPainter, tile: SampledTileRenderData) -> None:
    """Preserve native sample phase while scaling derived products."""
    if tile.integer_origin_sampling:
        painter.drawImage(
            round(tile.source_rect.x()),
            round(tile.source_rect.y()),
            tile.image,
        )
        return
    painter.drawImage(tile.source_rect, tile.image, tile.image_source_rect)


def _source_clips(
    item: SampledLayerRenderItem,
    panel_clips: tuple[QRectF, ...] | None,
) -> tuple[QRectF, ...] | None:
    """Map optional panel repair clips into sampled source space."""
    if panel_clips is None:
        return None
    inverse, invertible = item.transform.inverted()
    if not invertible:
        return ()
    return tuple(inverse.mapRect(panel_clip) for panel_clip in panel_clips)


__all__ = ["SampledItemCompositor"]
