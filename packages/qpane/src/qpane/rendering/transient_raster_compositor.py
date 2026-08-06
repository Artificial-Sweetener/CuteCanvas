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
"""Source-neutral composition of transient raster transform products."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QTransform

from ..scene.affine import LayerTransform
from ..scene.raster import RasterBounds
from ..scene.render_plan import (
    RasterLayerRenderItem,
    SampledLayerRenderItem,
    SceneRenderPlan,
    TransientRasterContribution,
    TransientRasterTransformContribution,
)
from .layer_isolation import LayerIsolationCompositor

_PrepareItem = Callable[
    [QPainter, SceneRenderPlan, RasterLayerRenderItem | SampledLayerRenderItem],
    None,
]
_DrawRasterSource = Callable[
    [QPainter, SceneRenderPlan, RasterLayerRenderItem],
    None,
]


class TransientRasterCompositor:
    """Apply immutable raster contributions at transient local geometry."""

    def __init__(self, isolation: LayerIsolationCompositor) -> None:
        """Share the renderer's bounded layer-isolation owner."""
        self._isolation = isolation

    def draw_isolated_item(
        self,
        painter: QPainter,
        plan: SceneRenderPlan,
        item: RasterLayerRenderItem,
        contribution: TransientRasterTransformContribution,
        *,
        draw_source: Callable[[QPainter], None],
        prepare_item: _PrepareItem,
    ) -> None:
        """Composite one transient raster independently from the backdrop."""

        def paint_layer(layer_painter: QPainter) -> None:
            """Render the durable source and contribution on one layer surface."""
            prepare_item(layer_painter, plan, item)
            self._apply_extent_clip(layer_painter, item, contribution)
            draw_source(layer_painter)
            self.apply(layer_painter, item, contribution)

        self._isolation.composite(
            painter,
            opacity=item.descriptor.opacity,
            paint_layer=paint_layer,
        )

    def draw_layer_group(
        self,
        painter: QPainter,
        plan: SceneRenderPlan,
        items: tuple[RasterLayerRenderItem, ...],
        contribution: TransientRasterContribution,
        *,
        prepare_item: _PrepareItem,
        draw_source: _DrawRasterSource,
    ) -> None:
        """Composite every sparse product for one transient layer as one surface."""
        if not items:
            return

        def paint_layer(layer_painter: QPainter) -> None:
            """Render grouped sources before applying the transient contribution."""
            for item in items:
                layer_painter.save()
                try:
                    prepare_item(layer_painter, plan, item)
                    draw_source(layer_painter, plan, item)
                finally:
                    layer_painter.restore()
            reference = items[0]
            layer_painter.save()
            try:
                prepare_item(layer_painter, plan, reference)
                if isinstance(
                    contribution,
                    TransientRasterTransformContribution,
                ):
                    self._apply_extent_clip(
                        layer_painter,
                        reference,
                        contribution,
                    )
                    self.apply(layer_painter, reference, contribution)
                else:
                    layer_painter.setCompositionMode(QPainter.CompositionMode_Source)
                    layer_painter.drawImage(
                        self.product_rect(reference, contribution.source_bounds),
                        contribution.source_image,
                    )
            finally:
                layer_painter.restore()

        self._isolation.composite(
            painter,
            opacity=items[0].descriptor.opacity,
            paint_layer=paint_layer,
        )

    def apply(
        self,
        painter: QPainter,
        item: RasterLayerRenderItem | SampledLayerRenderItem,
        contribution: TransientRasterTransformContribution,
    ) -> None:
        """Apply the source remainder and transformed destination contribution."""
        if contribution.source_patch is not None:
            painter.setCompositionMode(QPainter.CompositionMode_Source)
            painter.drawImage(
                self.product_rect(item, contribution.source_bounds),
                contribution.source_patch,
            )
        source_rect = self.product_rect(item, contribution.fragment_bounds)
        painter.save()
        try:
            painter.setTransform(
                self._product_transform(item, contribution.fragment_transform),
                True,
            )
            attenuation = contribution.destination_attenuation_mask
            if attenuation is not None:
                painter.setCompositionMode(QPainter.CompositionMode_DestinationOut)
                painter.drawImage(source_rect, attenuation)
                painter.setCompositionMode(QPainter.CompositionMode_Plus)
            else:
                painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.drawImage(source_rect, contribution.fragment_image)
        finally:
            painter.restore()

    @staticmethod
    def product_rect(
        item: RasterLayerRenderItem | SampledLayerRenderItem,
        bounds: RasterBounds,
    ) -> QRectF:
        """Map authoritative local bounds into one raster source product."""
        raster_bounds = item.descriptor.raster_bounds
        if (
            raster_bounds is None
            or raster_bounds.width <= 0
            or raster_bounds.height <= 0
        ):
            return QRectF()
        source_size = item.source_size
        scale_x = source_size.width() / raster_bounds.width
        scale_y = source_size.height() / raster_bounds.height
        return QRectF(
            (bounds.x - raster_bounds.x) * scale_x,
            (bounds.y - raster_bounds.y) * scale_y,
            bounds.width * scale_x,
            bounds.height * scale_y,
        )

    @staticmethod
    def _product_transform(
        item: RasterLayerRenderItem | SampledLayerRenderItem,
        transform: LayerTransform,
    ) -> QTransform:
        """Conjugate one local affine transform into product coordinates."""
        bounds = item.descriptor.raster_bounds
        if bounds is None:
            return QTransform()
        source_size = item.source_size
        scale_x = source_size.width() / bounds.width
        scale_y = source_size.height() / bounds.height
        product_to_local = QTransform()
        product_to_local.translate(float(bounds.x), float(bounds.y))
        product_to_local.scale(1.0 / scale_x, 1.0 / scale_y)
        local_to_product = product_to_local.inverted()[0]
        return product_to_local * transform.to_qtransform() * local_to_product

    def _apply_extent_clip(
        self,
        painter: QPainter,
        item: RasterLayerRenderItem | SampledLayerRenderItem,
        contribution: TransientRasterTransformContribution,
    ) -> None:
        """Apply the host-owned fixed-extent clip when one is present."""
        if contribution.extent_clip_bounds is not None:
            painter.setClipRect(
                self.product_rect(item, contribution.extent_clip_bounds),
                Qt.ClipOperation.IntersectClip,
            )
