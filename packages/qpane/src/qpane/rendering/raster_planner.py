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

"""Plan source-neutral raster primitives and visible tile work."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from math import isclose

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, QSizeF
from PySide6.QtGui import QImage, QTransform

from ..scene.identity import (
    SceneLayerAssetKey,
    SceneLayerTileKey,
    SourceRenderAssetKey,
    source_render_asset_key,
)
from ..scene.model import LayerClip, LayerPlacement
from ..scene.raster import RasterBounds
from ..scene.render_plan import (
    RasterLayerRenderItem,
    RenderStrategy,
    TileRenderData,
)
from ..scene.source_capabilities import (
    RasterPatchPresentationRegistry,
    RasterPresentationRegistry,
    RasterProductPolicy,
    RasterSourcePatch,
)
from .compiled_scene import CompiledRenderLayer, CompiledRenderScene
from .frame_geometry import RenderFrameGeometry
from .frame_projector import SceneFrameProjector
from .raster_products import RasterRenderProductStore
from .raster_sampling import (
    smooth_raster_sampling_enabled,
    smooth_raster_sampling_for_physical_scale,
)
from .render_tile_geometry import scale_bucket
from .scene_compiler import SceneRenderCompiler
from .tiles import TileManager
from .viewport import Viewport
from .visibility import visible_source_rect_for_layer

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RasterLayerGeometry:
    """Geometry mapping one layer's render-source pixels into the panel."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    asset_key: SceneLayerAssetKey
    pyramid_asset_key: SourceRenderAssetKey
    pyramid_scale: float
    transform: QTransform
    placement: LayerPlacement
    clip: LayerClip | None
    source_size: QSize
    tile_size: int
    tile_overlap: int
    visible_source_rect: QRectF

    def __post_init__(self) -> None:
        """Detach mutable Qt geometry from planner-owned frame values."""
        object.__setattr__(self, "transform", QTransform(self.transform))
        object.__setattr__(self, "source_size", QSize(self.source_size))
        object.__setattr__(
            self,
            "visible_source_rect",
            QRectF(self.visible_source_rect),
        )


@dataclass(frozen=True, slots=True)
class _RasterPlanningResult:
    """Raster primitive plus tile keys requested while building it."""

    item: RasterLayerRenderItem
    visible_tile_keys: frozenset[SceneLayerTileKey]


@dataclass(frozen=True, slots=True)
class _RasterSourceProduct:
    """One resolved raster sample and whether shared products may derive from it."""

    image: QImage
    scale: float
    cacheable: bool


@dataclass(frozen=True, slots=True)
class _TilePlan:
    """Tile payloads and worker-cancellation keys for one raster layer."""

    tiles_to_draw: tuple[TileRenderData, ...]
    visible_keys: frozenset[SceneLayerTileKey]
    max_tile_cols: int
    max_tile_rows: int
    visible_tile_range: tuple[int, int, int, int] | None


class RasterRenderPlanner:
    """Own viewport-dependent raster primitive and tile planning."""

    def __init__(
        self,
        *,
        compiler: SceneRenderCompiler,
        projector: SceneFrameProjector,
        products: RasterRenderProductStore,
        raster_sources: RasterPresentationRegistry,
        raster_patches: RasterPatchPresentationRegistry,
        tile_manager_provider: Callable[[], TileManager],
        viewport: Viewport,
    ) -> None:
        """Capture source, geometry, tile, and viewport collaborators."""
        self._compiler = compiler
        self._projector = projector
        self._products = products
        self._raster_sources = raster_sources
        self._raster_patches = raster_patches
        self._tile_manager_provider = tile_manager_provider
        self._viewport = viewport

    @property
    def _tile_manager(self) -> TileManager:
        """Return the presenter's current authoritative tile manager."""
        return self._tile_manager_provider()

    def build_frame_items(
        self,
        compiled: CompiledRenderScene,
        frame: RenderFrameGeometry,
        *,
        layers: tuple[CompiledRenderLayer, ...] | None = None,
    ) -> tuple[RasterLayerRenderItem, ...]:
        """Build ordered raster primitives for one viewport frame."""
        planned_layers = compiled.layers if layers is None else layers
        results = tuple(
            result
            for layer in planned_layers
            for result in self._build_layer_items(
                compiled=compiled,
                layer=layer,
                frame=frame,
            )
        )
        visible_tile_keys = frozenset(
            key for result in results for key in result.visible_tile_keys
        )
        if hasattr(self._tile_manager, "cancel_invisible_workers"):
            self._tile_manager.cancel_invisible_workers(visible_tile_keys)
        return tuple(result.item for result in results)

    def dirty_rect_for_tile_key(
        self,
        key: SceneLayerTileKey,
        *,
        compiled: CompiledRenderScene,
        frame: RenderFrameGeometry,
    ) -> QRect | None:
        """Return panel damage for a ready visible tile."""
        for geometry in self.layer_geometries(compiled=compiled, frame=frame):
            if geometry.asset_key != key.asset_key:
                continue
            if geometry.pyramid_asset_key != key.pyramid_asset_key:
                return None
            if abs(key.pyramid_scale - geometry.pyramid_scale) > 1e-6:
                return None
            source_rect = QRectF(
                self.tile_draw_position(key),
                QSizeF(geometry.tile_size, geometry.tile_size),
            )
            visible_source_rect = source_rect.intersected(geometry.visible_source_rect)
            if visible_source_rect.isEmpty():
                return None
            return (
                geometry.transform.mapRect(visible_source_rect)
                .adjusted(-1, -1, 1, 1)
                .toAlignedRect()
            )
        return None

    def layer_geometries(
        self,
        *,
        compiled: CompiledRenderScene,
        frame: RenderFrameGeometry,
    ) -> tuple[RasterLayerGeometry, ...]:
        """Return visible raster geometry without requesting tile payloads."""
        qpane_rect = QRectF(frame.qpane_rect)
        return tuple(
            geometry
            for layer in compiled.layers
            for geometry in self._layer_geometries(
                compiled=compiled,
                layer=layer,
                frame=frame,
                qpane_rect=qpane_rect,
            )
        )

    def _layer_geometries(
        self,
        *,
        compiled: CompiledRenderScene,
        layer: CompiledRenderLayer,
        frame: RenderFrameGeometry,
        qpane_rect: QRectF,
    ) -> tuple[RasterLayerGeometry, ...]:
        """Return ordinary geometry for each sparse patch or dense source."""
        patch_layers = self._patch_layers(compiled, layer, frame)
        candidates = ((layer, None),) if patch_layers is None else patch_layers
        geometries: list[RasterLayerGeometry] = []
        for candidate, patch in candidates:
            source_product = (
                self._source_image(compiled, candidate, frame)
                if patch is None
                else self._patch_product(candidate, patch, frame)
            )
            if source_product is None:
                continue
            geometry = self._layer_geometry_for_product(
                compiled=compiled,
                layer=candidate,
                frame=frame,
                qpane_rect=qpane_rect,
                source_product=source_product,
            )
            if geometry is not None:
                geometries.append(geometry)
        return tuple(geometries)

    def tile_draw_position(self, key: SceneLayerTileKey) -> QPointF:
        """Return a tile's upper-left source coordinate."""
        stride = self._tile_manager.tile_size - self._tile_manager.tile_overlap
        return QPointF(key.col * stride, key.row * stride)

    def _layer_geometry(
        self,
        *,
        compiled: CompiledRenderScene,
        layer: CompiledRenderLayer,
        frame: RenderFrameGeometry,
        qpane_rect: QRectF,
    ) -> RasterLayerGeometry | None:
        """Resolve one compiled raster layer's visible panel geometry."""
        source_product = self._source_image(compiled, layer, frame)
        if source_product is None:
            return None
        return self._layer_geometry_for_product(
            compiled=compiled,
            layer=layer,
            frame=frame,
            qpane_rect=qpane_rect,
            source_product=source_product,
        )

    def _layer_geometry_for_product(
        self,
        *,
        compiled: CompiledRenderScene,
        layer: CompiledRenderLayer,
        frame: RenderFrameGeometry,
        qpane_rect: QRectF,
        source_product: _RasterSourceProduct,
    ) -> RasterLayerGeometry | None:
        """Resolve geometry from one already sampled dense or sparse product."""
        source_image = source_product.image
        pyramid_scale = source_product.scale
        transform = self._transform_for_layer(
            compiled=compiled,
            layer=layer,
            source_image=source_image,
            pyramid_scale=pyramid_scale,
            frame=frame,
        )
        visibility = visible_source_rect_for_layer(
            scene_bounds=compiled.scene.bounds,
            layer_placement=layer.descriptor.placement,
            source_size=source_image.size(),
            visible_scene_rect=frame.visible_scene_rect,
            clip=layer.descriptor.clip,
            viewport_rect=qpane_rect,
            item_transform=transform,
        )
        if visibility is None:
            return None
        return RasterLayerGeometry(
            scene_id=compiled.scene.scene_id,
            layer_id=layer.descriptor.layer_id,
            asset_key=layer.asset_key,
            pyramid_asset_key=layer.pyramid_asset_key,
            pyramid_scale=pyramid_scale,
            transform=transform,
            placement=layer.descriptor.placement,
            clip=layer.descriptor.clip,
            source_size=source_image.size(),
            tile_size=frame.tile_size,
            tile_overlap=frame.tile_overlap,
            visible_source_rect=visibility.source_rect,
        )

    def _build_item(
        self,
        *,
        compiled: CompiledRenderScene,
        layer: CompiledRenderLayer,
        frame: RenderFrameGeometry,
    ) -> _RasterPlanningResult | None:
        """Build one raster primitive and its requested tile identities."""
        source_product = self._source_image(compiled, layer, frame)
        if source_product is None:
            return None
        return self._build_product_item(
            compiled=compiled,
            layer=layer,
            frame=frame,
            source_product=source_product,
        )

    def _build_layer_items(
        self,
        *,
        compiled: CompiledRenderScene,
        layer: CompiledRenderLayer,
        frame: RenderFrameGeometry,
    ) -> tuple[_RasterPlanningResult, ...]:
        """Build one dense item or multiple ordinary sparse-patch items."""
        patch_layers = self._patch_layers(compiled, layer, frame)
        if patch_layers is None:
            result = self._build_item(compiled=compiled, layer=layer, frame=frame)
            return () if result is None else (result,)
        results: list[_RasterPlanningResult] = []
        for patch_layer, patch in patch_layers:
            source_product = self._patch_product(patch_layer, patch, frame)
            if source_product is None:
                continue
            result = self._build_product_item(
                compiled=compiled,
                layer=patch_layer,
                frame=frame,
                source_product=source_product,
                source_clip_bounds=(
                    patch.bounds if patch.sample_bounds != patch.bounds else None
                ),
            )
            if result is not None:
                results.append(result)
        return tuple(results)

    def _build_product_item(
        self,
        *,
        compiled: CompiledRenderScene,
        layer: CompiledRenderLayer,
        frame: RenderFrameGeometry,
        source_product: _RasterSourceProduct,
        source_clip_bounds: RasterBounds | None = None,
    ) -> _RasterPlanningResult | None:
        """Build the sole raster primitive from one resolved source product."""
        source_image = source_product.image
        pyramid_scale = source_product.scale
        strategy = self._render_strategy(layer, frame, source_product)
        transform = self._transform_for_layer(
            compiled=compiled,
            layer=layer,
            source_image=source_image,
            pyramid_scale=pyramid_scale,
            frame=frame,
        )
        tile_plan = self._tile_plan(
            compiled=compiled,
            layer=layer,
            frame=frame,
            source_image=source_image,
            pyramid_scale=pyramid_scale,
            transform=transform,
            strategy=strategy,
        )
        device_pixel_ratio = frame.device_pixel_ratio
        relative_base_raster_scale = max(frame.zoom, 0.0) / max(
            frame.native_zoom,
            1e-9,
        )
        render_hint_enabled = (
            smooth_raster_sampling_for_physical_scale(relative_base_raster_scale)
            if layer.is_base_raster
            else smooth_raster_sampling_enabled(transform, device_pixel_ratio)
        )
        descriptor_bounds = layer.descriptor.raster_bounds
        source_clip_rect = None
        if source_clip_bounds is not None and descriptor_bounds is not None:
            scale_x = source_image.width() / descriptor_bounds.width
            scale_y = source_image.height() / descriptor_bounds.height
            source_clip_rect = QRectF(
                (source_clip_bounds.x - descriptor_bounds.x) * scale_x,
                (source_clip_bounds.y - descriptor_bounds.y) * scale_y,
                source_clip_bounds.width * scale_x,
                source_clip_bounds.height * scale_y,
            )
        return _RasterPlanningResult(
            item=RasterLayerRenderItem(
                descriptor=layer.descriptor,
                source_image=source_image,
                asset_key=layer.asset_key,
                pyramid_asset_key=layer.pyramid_asset_key,
                pyramid_scale=pyramid_scale,
                transform=transform,
                placement=layer.descriptor.placement,
                clip=layer.descriptor.clip,
                strategy=strategy,
                render_hint_enabled=render_hint_enabled,
                debug_draw_tile_grid=frame.debug_draw_tile_grid,
                tiles_to_draw=tile_plan.tiles_to_draw,
                tile_size=frame.tile_size,
                tile_overlap=frame.tile_overlap,
                max_tile_cols=tile_plan.max_tile_cols,
                max_tile_rows=tile_plan.max_tile_rows,
                visible_tile_range=tile_plan.visible_tile_range,
                is_base_raster=layer.is_base_raster,
                source_clip_rect=source_clip_rect,
            ),
            visible_tile_keys=tile_plan.visible_keys,
        )

    def _patch_layers(
        self,
        compiled: CompiledRenderScene,
        layer: CompiledRenderLayer,
        frame: RenderFrameGeometry,
    ) -> tuple[tuple[CompiledRenderLayer, RasterSourcePatch], ...] | None:
        """Adapt visible sparse products into ordinary compiled raster layers."""
        owner = self._raster_patches.owner_for(layer.descriptor.source)
        local_bounds = self._visible_local_bounds(compiled, layer, frame)
        if owner is None:
            return None
        if local_bounds is None:
            return ()
        patches = owner.source_patches(layer.descriptor.source, local_bounds)
        if patches is None:
            return None
        transformed: list[tuple[CompiledRenderLayer, RasterSourcePatch]] = []
        for patch in patches:
            if patch.image.isNull() or layer.descriptor.transform is None:
                continue
            sample_bounds = patch.sample_bounds
            if sample_bounds is None:
                continue
            descriptor = replace(
                layer.descriptor,
                raster_bounds=sample_bounds,
                placement=layer.descriptor.transform.map_bounds(sample_bounds),
            )
            patch_id = uuid.uuid5(
                layer.pyramid_asset_key.source_id,
                f"patch:{patch.bounds.x}:{patch.bounds.y}:{patch.bounds.width}:{patch.bounds.height}",
            )
            product_key = source_render_asset_key(
                source_id=patch_id,
                source_kind=f"{layer.pyramid_asset_key.source_kind}-patch",
                revision=layer.pyramid_asset_key.source_revision,
                source_path=layer.pyramid_asset_key.source_path,
            )
            transformed.append(
                (
                    replace(
                        layer,
                        descriptor=descriptor,
                        pyramid_asset_key=product_key,
                        source_size=patch.image.size(),
                        uses_default_base_tile_math=False,
                    ),
                    patch,
                )
            )
        return tuple(transformed)

    def _visible_local_bounds(
        self,
        compiled: CompiledRenderScene,
        layer: CompiledRenderLayer,
        frame: RenderFrameGeometry,
    ) -> RasterBounds | None:
        """Project the finite canvas/viewport intersection into layer-local space."""
        descriptor = layer.descriptor
        transform = descriptor.transform
        raster_bounds = descriptor.raster_bounds
        inverse = None if transform is None else transform.inverted()
        if inverse is None or raster_bounds is None:
            return None
        scene_rect = QRectF(
            compiled.scene.bounds.x,
            compiled.scene.bounds.y,
            compiled.scene.bounds.width,
            compiled.scene.bounds.height,
        ).intersected(frame.visible_scene_rect)
        if scene_rect.isEmpty():
            return None
        local_rect = inverse.map_rect(scene_rect).toAlignedRect()
        if local_rect.isEmpty():
            return None
        return raster_bounds.intersection(RasterBounds.from_qrect(local_rect))

    def _patch_product(
        self,
        layer: CompiledRenderLayer,
        patch: RasterSourcePatch,
        frame: RenderFrameGeometry,
    ) -> _RasterSourceProduct | None:
        """Select shared LOD for one sparse patch through the common product store."""
        image = patch.image
        if image.isNull():
            return None
        policy = self._raster_sources.product_policy(layer.descriptor.source)
        if policy is RasterProductPolicy.VOLATILE:
            return _RasterSourceProduct(image=image, scale=1.0, cacheable=False)
        selected = self._products.best_fit_image(
            asset_key=layer.pyramid_asset_key,
            full_image=image,
            target_width=layer.descriptor.placement.width * frame.zoom,
        )
        scale = selected.width() / image.width() if image.width() > 0 else 1.0
        return _RasterSourceProduct(image=selected, scale=scale, cacheable=True)

    def _source_image(
        self,
        compiled: CompiledRenderScene,
        layer: CompiledRenderLayer,
        frame: RenderFrameGeometry,
    ) -> _RasterSourceProduct | None:
        """Resolve the best-fit image and its scale from authoritative pixels."""
        source = layer.descriptor.source
        layer_to_panel = self._projector.layer_to_panel(
            scene=compiled.scene,
            layer=layer.descriptor,
            source_size=layer.source_size,
            frame=frame,
        )
        requested_scale = min(
            1.0,
            scale_bucket(layer_to_panel, frame.device_pixel_ratio),
        )
        target_width = layer.source_size.width() * requested_scale
        policy = self._raster_sources.product_policy(source)
        if policy is RasterProductPolicy.VOLATILE:
            sampled_image = self._raster_sources.source_image(
                source,
                scale=requested_scale,
            )
            return self._direct_product(sampled_image, layer.source_size)

        full_image = self._raster_sources.source_image(source)
        if full_image is None or full_image.isNull():
            sampled_image = self._products.sampled_image(
                asset_key=layer.pyramid_asset_key,
                source_width=layer.source_size.width(),
                target_width=target_width,
                producer=lambda scale: self._raster_sources.source_image(
                    source,
                    scale=scale,
                ),
            )
            return self._direct_product(sampled_image, layer.source_size)
        if full_image.size() != layer.source_size:
            return self._direct_product(full_image, layer.source_size)
        source_image = self._products.best_fit_image(
            asset_key=layer.pyramid_asset_key,
            full_image=full_image,
            target_width=target_width,
        )
        pyramid_scale = (
            source_image.width() / layer.source_size.width()
            if layer.source_size.width() > 0
            else 1.0
        )
        return _RasterSourceProduct(
            image=source_image,
            scale=pyramid_scale,
            cacheable=True,
        )

    @staticmethod
    def _direct_product(
        image: QImage | None,
        source_size: QSize,
    ) -> _RasterSourceProduct | None:
        """Return one uncached sampled product with its authoritative scale."""
        if image is None or image.isNull():
            return None
        pyramid_scale = (
            image.width() / source_size.width() if source_size.width() > 0 else 1.0
        )
        return _RasterSourceProduct(
            image=image,
            scale=pyramid_scale,
            cacheable=False,
        )

    @staticmethod
    def _render_strategy(
        layer: CompiledRenderLayer,
        frame: RenderFrameGeometry,
        source_product: _RasterSourceProduct,
    ) -> RenderStrategy:
        """Return the direct or tiled strategy for a layer in one frame."""
        if not source_product.cacheable:
            return RenderStrategy.DIRECT
        canvas_size_physical = (
            QSizeF(
                layer.descriptor.placement.width,
                layer.descriptor.placement.height,
            )
            * frame.zoom
        )
        viewport_size_physical = frame.physical_viewport_rect.size()
        if (
            canvas_size_physical.width() > viewport_size_physical.width()
            or canvas_size_physical.height() > viewport_size_physical.height()
        ):
            return RenderStrategy.TILE
        return RenderStrategy.DIRECT

    def _transform_for_layer(
        self,
        *,
        compiled: CompiledRenderScene,
        layer: CompiledRenderLayer,
        source_image: QImage,
        pyramid_scale: float,
        frame: RenderFrameGeometry,
    ) -> QTransform:
        """Return the source-to-panel transform for a compiled raster layer."""
        if layer.uses_default_base_tile_math:
            return self._viewport.get_transform(
                source_image.size(),
                pyramid_scale,
                pan_override=frame.current_pan,
                content_snapshot=frame.content_snapshot,
            )
        return self._projector.layer_to_panel(
            scene=compiled.scene,
            layer=layer.descriptor,
            source_size=source_image.size(),
            frame=frame,
        )

    def _tile_plan(
        self,
        *,
        compiled: CompiledRenderScene,
        layer: CompiledRenderLayer,
        frame: RenderFrameGeometry,
        source_image: QImage,
        pyramid_scale: float,
        transform: QTransform,
        strategy: RenderStrategy,
    ) -> _TilePlan:
        """Return tile payloads and visible identities for one raster layer."""
        if strategy == RenderStrategy.DIRECT:
            return _TilePlan((), frozenset(), 0, 0, None)
        max_cols, max_rows = self._tile_manager.grid.dimensions_for(
            source_image.width(),
            source_image.height(),
        )
        visible_source_rect = self._visible_source_rect(
            compiled=compiled,
            layer=layer,
            frame=frame,
            source_image=source_image,
            pyramid_scale=pyramid_scale,
            transform=transform,
        )
        visible_range = self._tile_range(
            source_rect=visible_source_rect,
            tile_size=frame.tile_size,
            tile_overlap=frame.tile_overlap,
            max_cols=max_cols,
            max_rows=max_rows,
        )
        tiles_to_draw: list[TileRenderData] = []
        visible_keys: set[SceneLayerTileKey] = set()
        start_row, end_row, start_col, end_col = visible_range
        for row in range(start_row, end_row + 1):
            for col in range(start_col, end_col + 1):
                tile_key = SceneLayerTileKey(
                    asset_key=layer.asset_key,
                    pyramid_asset_key=layer.pyramid_asset_key,
                    pyramid_scale=pyramid_scale,
                    tile_size=frame.tile_size,
                    tile_overlap=frame.tile_overlap,
                    row=row,
                    col=col,
                )
                visible_keys.add(tile_key)
                tile_image = self._tile_manager.get_tile(tile_key, source_image)
                if tile_image:
                    tiles_to_draw.append(
                        TileRenderData(tile_image, self.tile_draw_position(tile_key))
                    )
        return _TilePlan(
            tuple(tiles_to_draw),
            frozenset(visible_keys),
            max_cols,
            max_rows,
            visible_range,
        )

    def _visible_source_rect(
        self,
        *,
        compiled: CompiledRenderScene,
        layer: CompiledRenderLayer,
        frame: RenderFrameGeometry,
        source_image: QImage,
        pyramid_scale: float,
        transform: QTransform,
    ) -> QRectF:
        """Return the source region visible for tiled rendering."""
        if layer.uses_default_base_tile_math:
            return self._default_visible_source_rect(
                source_size=source_image.size(),
                pyramid_scale=pyramid_scale,
                frame=frame,
            )
        visibility = visible_source_rect_for_layer(
            scene_bounds=compiled.scene.bounds,
            layer_placement=layer.descriptor.placement,
            source_size=source_image.size(),
            visible_scene_rect=frame.visible_scene_rect,
            clip=layer.descriptor.clip,
            viewport_rect=QRectF(frame.qpane_rect),
            item_transform=transform,
        )
        return visibility.source_rect if visibility is not None else QRectF()

    @staticmethod
    def _default_visible_source_rect(
        *,
        source_size: QSize,
        pyramid_scale: float,
        frame: RenderFrameGeometry,
    ) -> QRectF:
        """Return visible source pixels for a full-scene base image."""
        safe_zoom = frame.zoom if not isclose(frame.zoom, 0.0) else 1.0
        safe_pyramid_scale = pyramid_scale if pyramid_scale > 0.0 else 1.0
        effective_zoom = safe_zoom / safe_pyramid_scale
        if isclose(effective_zoom, 0.0):
            effective_zoom = 1.0
        viewport_center = QPointF(frame.physical_viewport_rect.center())
        source_center = QPointF(source_size.width() / 2.0, source_size.height() / 2.0)
        top_left = (
            frame.physical_viewport_rect.topLeft() - viewport_center - frame.current_pan
        ) / effective_zoom + source_center
        bottom_right = (
            frame.physical_viewport_rect.bottomRight()
            - viewport_center
            - frame.current_pan
        ) / effective_zoom + source_center
        return (
            QRectF(top_left, bottom_right)
            .normalized()
            .intersected(
                QRectF(
                    0.0, 0.0, float(source_size.width()), float(source_size.height())
                )
            )
        )

    @staticmethod
    def _tile_range(
        *,
        source_rect: QRectF,
        tile_size: int,
        tile_overlap: int,
        max_cols: int,
        max_rows: int,
    ) -> tuple[int, int, int, int]:
        """Return inclusive tile bounds for a visible source rectangle."""
        if source_rect.isEmpty() or max_cols <= 0 or max_rows <= 0:
            return 0, -1, 0, -1
        stride = tile_size - tile_overlap
        if stride <= 0:
            logger.error(
                "Tile stride is non-positive; size=%s overlap=%s max_cols=%s max_rows=%s",
                tile_size,
                tile_overlap,
                max_cols,
                max_rows,
            )
            return 0, -1, 0, -1
        start_col = max(0, int(source_rect.left() / stride) - 1)
        start_row = max(0, int(source_rect.top() / stride) - 1)
        end_col = min(max_cols - 1, int(source_rect.right() / stride) + 1)
        end_row = min(max_rows - 1, int(source_rect.bottom() / stride) + 1)
        if start_col > end_col or start_row > end_row:
            return 0, -1, 0, -1
        return start_row, end_row, start_col, end_col
