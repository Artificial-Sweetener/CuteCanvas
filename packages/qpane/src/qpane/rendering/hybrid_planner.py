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
"""Frame planning for asynchronously sampled hybrid render sources."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QImage, QTransform

from ..hybrid.model import HybridRasterPrimitive
from ..hybrid.tile_source import HybridRenderTileSource
from ..scene.identity import source_render_asset_key
from ..scene.model import LayerDescriptor, LayerKind
from ..scene.raster import RasterBounds
from ..scene.render_plan import SampledLayerRenderItem, SampledTileRenderData
from .compiled_scene import CompiledRenderScene
from .frame_geometry import RenderFrameGeometry
from .frame_projector import SceneFrameProjector
from .raster_products import RasterRenderProductStore
from .raster_sampling import (
    raster_sample_scale_limit,
    smooth_raster_sampling_enabled,
)
from .render_tile_geometry import scale_bucket
from .render_tile_types import RenderTileBatchSource
from .render_tiles import RenderTileWorkCoordinator
from .sampled_atlas import compact_native_sampled_tiles
from .sampled_lattice import (
    sampled_source_lattice,
    source_sampling_phase_is_fractional,
)
from .sampled_projection_fallback import reproject_sampled_fallback
from .sdk import HybridSource


@dataclass(frozen=True, slots=True)
class SampledFramePlan:
    """Carry sampled items plus layers awaiting their first complete product."""

    items: tuple[SampledLayerRenderItem, ...]
    pending_layer_ids: frozenset[uuid.UUID] = frozenset()
    projection_fallbacks: tuple[SampledLayerRenderItem, ...] = ()


class HybridRenderPlanner:
    """Compile visible hybrid documents into atomic sampled tile batches."""

    def __init__(
        self,
        *,
        projector: SceneFrameProjector,
        refinement: RenderTileWorkCoordinator,
        products: RasterRenderProductStore,
    ) -> None:
        """Bind hybrid snapshots, frame projection, and shared refinement."""
        self._projector = projector
        self._refinement = refinement
        self._products = products

    def build_frame_items(
        self,
        compiled: CompiledRenderScene,
        frame: RenderFrameGeometry,
        *,
        transient_support_bounds: Mapping[uuid.UUID, RasterBounds] | None = None,
        prior_items: Mapping[uuid.UUID, SampledLayerRenderItem] | None = None,
    ) -> SampledFramePlan:
        """Return sampled primitives for every compiled hybrid layer."""
        support_bounds_by_layer = transient_support_bounds or {}
        previous_items = prior_items or {}
        items: list[SampledLayerRenderItem] = []
        projection_fallbacks: list[SampledLayerRenderItem] = []
        pending_layer_ids: set[uuid.UUID] = set()
        for compiled_layer in compiled.hybrid_layers:
            layer = compiled_layer.descriptor
            snapshot = compiled_layer.snapshot
            if not isinstance(snapshot, HybridSource):
                continue
            document = snapshot.document
            source_size = QSize(document.bounds.width, document.bounds.height)
            layer_to_panel = self._projector.layer_to_panel(
                scene=compiled.scene,
                layer=layer,
                source_size=source_size,
                frame=frame,
            )
            render_hint_enabled = smooth_raster_sampling_enabled(
                layer_to_panel,
                frame.device_pixel_ratio,
            )
            if not document.primitives:
                if layer.layer_id in support_bounds_by_layer:
                    support = self._transient_support_item(
                        layer,
                        source_size,
                        layer_to_panel,
                        render_hint_enabled,
                        support_bounds_by_layer[layer.layer_id],
                        frame.device_pixel_ratio,
                    )
                    if support is not None:
                        items.append(support)
                continue
            raster_only = all(
                isinstance(primitive, HybridRasterPrimitive)
                for primitive in document.primitives
            )
            raster_backed_mask = layer.kind is LayerKind.MASK and any(
                isinstance(primitive, HybridRasterPrimitive)
                for primitive in document.primitives
            )
            native_phase_stable = raster_only or raster_backed_mask
            refinement = self._refinement.request(
                source=HybridRenderTileSource(
                    document,
                    snapshot.style,
                    snapshot.presentation_revision,
                ),
                source_to_panel=layer_to_panel,
                panel_rect=frame.sampling_panel_rect,
                device_pixel_ratio=frame.device_pixel_ratio,
                maximum_scale=(
                    1.0
                    if native_phase_stable
                    else raster_sample_scale_limit(
                        layer_to_panel,
                        frame.device_pixel_ratio,
                    )
                ),
            )
            products = refinement.products
            if refinement.pending:
                pending_layer_ids.add(layer.layer_id)
            if products is None:
                fallback = reproject_sampled_fallback(
                    previous_items,
                    descriptor=layer,
                    transform=layer_to_panel,
                    source_size=source_size,
                    render_hint_enabled=render_hint_enabled,
                )
                if fallback is not None:
                    projection_fallbacks.append(fallback)
                continue
            tiles = tuple(
                SampledTileRenderData(
                    product.image,
                    product.source_rect,
                    product.image_source_rect,
                )
                for product in products
            )
            source_bounds = None
            if native_phase_stable and source_sampling_phase_is_fractional(
                layer_to_panel,
                frame.device_pixel_ratio,
            ):
                lattice = sampled_source_lattice(
                    descriptor=layer,
                    source_size=source_size,
                    source_to_panel=layer_to_panel,
                    panel_rect=frame.sampling_panel_rect,
                )
                if lattice is not None:
                    atlas = compact_native_sampled_tiles(
                        products=self._products,
                        asset_key=source_render_asset_key(
                            source_id=document.source_id,
                            source_kind="hybrid",
                            revision=snapshot.revision,
                            source_path=None,
                        ),
                        product_identity=tuple(product.key for product in products),
                        atlas_rect=lattice.source_rect,
                        tiles=tiles,
                    )
                    if atlas is not None:
                        tiles = (atlas,)
                        source_bounds = atlas.source_rect
            support_bounds = support_bounds_by_layer.get(layer.layer_id)
            if support_bounds is not None:
                support_scale_x, support_scale_y = _support_sample_scale(
                    tiles,
                    layer_to_panel,
                    frame.device_pixel_ratio,
                    support_bounds,
                )
                support_tile = self._transient_support_tile(
                    layer,
                    source_size,
                    support_bounds,
                    support_scale_x,
                    support_scale_y,
                )
                if support_tile is not None:
                    tiles = (*tiles, support_tile)
            items.append(
                SampledLayerRenderItem(
                    descriptor=layer,
                    transform=layer_to_panel,
                    placement=layer.placement,
                    clip=layer.clip,
                    source_size=source_size,
                    render_hint_enabled=render_hint_enabled,
                    tiles=tiles,
                    source_bounds=source_bounds,
                )
            )
        for compiled_layer in compiled.sampled_layers:
            source = compiled_layer.snapshot
            if not isinstance(source, RenderTileBatchSource):
                continue
            item, pending, projection_fallback = self._sampled_item(
                compiled,
                frame,
                compiled_layer.descriptor,
                source,
                prior_items=previous_items,
            )
            if pending:
                pending_layer_ids.add(compiled_layer.descriptor.layer_id)
            if item is not None:
                items.append(item)
            if projection_fallback is not None:
                projection_fallbacks.append(projection_fallback)
        return SampledFramePlan(
            tuple(items),
            frozenset(pending_layer_ids),
            tuple(projection_fallbacks),
        )

    @staticmethod
    def _transient_support_item(
        layer: LayerDescriptor,
        source_size: QSize,
        layer_to_panel: QTransform,
        render_hint_enabled: bool,
        support_bounds: RasterBounds,
        device_pixel_ratio: float,
    ) -> SampledLayerRenderItem | None:
        """Build a bounded empty source lattice for one active transient edit."""
        support_scale = min(
            1.0,
            scale_bucket(
                layer_to_panel,
                device_pixel_ratio,
                QRectF(
                    support_bounds.x,
                    support_bounds.y,
                    support_bounds.width,
                    support_bounds.height,
                ),
            ),
        )
        tile = HybridRenderPlanner._transient_support_tile(
            layer,
            source_size,
            support_bounds,
            support_scale,
            support_scale,
        )
        if tile is None:
            return None
        return SampledLayerRenderItem(
            descriptor=layer,
            transform=layer_to_panel,
            placement=layer.placement,
            clip=layer.clip,
            source_size=source_size,
            render_hint_enabled=render_hint_enabled,
            tiles=(tile,),
            source_bounds=tile.source_rect,
        )

    @staticmethod
    def _transient_support_tile(
        layer: LayerDescriptor,
        source_size: QSize,
        support_bounds: RasterBounds,
        scale_x: float,
        scale_y: float,
    ) -> SampledTileRenderData | None:
        """Build transparent sampled support for provisional local coverage."""
        if scale_x <= 0.0 or scale_y <= 0.0:
            raise ValueError("transient support sample scales must be positive")
        local_bounds = layer.raster_bounds or RasterBounds.from_size(source_size)
        clipped_bounds = support_bounds.intersection(local_bounds)
        if clipped_bounds is None:
            return None
        local_to_source_x = source_size.width() / local_bounds.width
        local_to_source_y = source_size.height() / local_bounds.height
        source_rect = QRectF(
            (clipped_bounds.x - local_bounds.x) * local_to_source_x,
            (clipped_bounds.y - local_bounds.y) * local_to_source_y,
            clipped_bounds.width * local_to_source_x,
            clipped_bounds.height * local_to_source_y,
        )
        image = QImage(
            max(1, round(source_rect.width() * scale_x)),
            max(1, round(source_rect.height() * scale_y)),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        image.fill(Qt.GlobalColor.transparent)
        return SampledTileRenderData(
            image,
            source_rect,
            QRectF(image.rect()),
        )

    def _sampled_item(
        self,
        compiled: CompiledRenderScene,
        frame: RenderFrameGeometry,
        layer: LayerDescriptor,
        source: RenderTileBatchSource,
        *,
        prior_items: Mapping[uuid.UUID, SampledLayerRenderItem],
    ) -> tuple[
        SampledLayerRenderItem | None,
        bool,
        SampledLayerRenderItem | None,
    ]:
        """Plan one generic sampled source through the shared tile coordinator."""
        source_size = QSize(source.bounds.width, source.bounds.height)
        layer_to_panel = self._projector.layer_to_panel(
            scene=compiled.scene,
            layer=layer,
            source_size=source_size,
            frame=frame,
        )
        render_hint_enabled = smooth_raster_sampling_enabled(
            layer_to_panel,
            frame.device_pixel_ratio,
        )
        refinement = self._refinement.request(
            source=source,
            source_to_panel=layer_to_panel,
            panel_rect=frame.sampling_panel_rect,
            device_pixel_ratio=frame.device_pixel_ratio,
            maximum_scale=raster_sample_scale_limit(
                layer_to_panel,
                frame.device_pixel_ratio,
            ),
        )
        if refinement.products is None:
            return (
                None,
                refinement.pending,
                reproject_sampled_fallback(
                    prior_items,
                    descriptor=layer,
                    transform=layer_to_panel,
                    source_size=source_size,
                    render_hint_enabled=render_hint_enabled,
                ),
            )
        products = refinement.products or ()
        return (
            SampledLayerRenderItem(
                descriptor=layer,
                transform=layer_to_panel,
                placement=layer.placement,
                clip=layer.clip,
                source_size=source_size,
                render_hint_enabled=render_hint_enabled,
                tiles=tuple(
                    SampledTileRenderData(
                        product.image,
                        product.source_rect,
                        product.image_source_rect,
                    )
                    for product in products
                ),
            ),
            refinement.pending,
            None,
        )


def _support_sample_scale(
    tiles: tuple[SampledTileRenderData, ...],
    layer_to_panel: QTransform,
    device_pixel_ratio: float,
    support_bounds: RasterBounds,
) -> tuple[float, float]:
    """Return the sampled density shared by durable and support products."""
    for tile in tiles:
        if tile.source_rect.width() > 0.0 and tile.source_rect.height() > 0.0:
            return (
                tile.image_source_rect.width() / tile.source_rect.width(),
                tile.image_source_rect.height() / tile.source_rect.height(),
            )
    scale = min(
        1.0,
        scale_bucket(
            layer_to_panel,
            device_pixel_ratio,
            QRectF(
                support_bounds.x,
                support_bounds.y,
                support_bounds.width,
                support_bounds.height,
            ),
        ),
    )
    return scale, scale
