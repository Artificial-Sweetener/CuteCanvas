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
from math import isclose

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, QSizeF, Qt
from PySide6.QtGui import QImage, QPainter

from ..core import Config
from ..scene.identity import SceneLayerTileKey, source_render_asset_key
from ..scene.raster import RasterBounds
from ..scene.raster_sampling import RasterPresentationSampling
from ..scene.render_plan import (
    RasterLayerRenderItem,
    RenderStrategy,
    SampledLayerRenderItem,
    SampledTileRenderData,
    TileRenderData,
)
from ..scene.source_capabilities import (
    RasterPatchPresentationRegistry,
    RasterPresentation,
    RasterPresentationRegistry,
    RasterProductPolicy,
    RasterSourcePatch,
)
from .compiled_scene import CompiledRenderLayer, CompiledRenderScene
from .exact_raster_refinement import ExactRasterRefinementPlanner, exact_frame_is_ready
from .frame_geometry import RenderFrameGeometry
from .frame_projector import SceneFrameProjector
from .panel_mapping import PanelLayerMapping
from .projective_visibility import visible_scene_raster_bounds
from .raster_planning_products import (
    RasterLayerGeometry,
    RasterPlanningResult,
    RasterSourceProduct,
    RasterTilePlan,
)
from .raster_products import RasterRenderProductStore
from .raster_sampling import (
    raster_presentation_sampling,
    raster_presentation_sampling_for_source_scale,
)
from .render_tile_geometry import scale_bucket
from .render_tiles import RenderTileWorkCoordinator
from .sampled_lattice import (
    sampled_source_lattice,
    source_sampling_phase_is_fractional,
)
from .scene_compiler import SceneRenderCompiler
from .tiles import TileManager
from .viewport import Viewport
from .visibility import visible_source_rect_for_layer

logger = logging.getLogger(__name__)

_MAX_SPARSE_ATLAS_PIXELS = 4 * 1024 * 1024
_MAX_SPARSE_ATLAS_EXPANSION = 4


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
        refinement: RenderTileWorkCoordinator,
        tile_manager_provider: Callable[[], TileManager],
        viewport: Viewport,
    ) -> None:
        """Capture source, geometry, tile, and viewport collaborators."""
        self._compiler = compiler
        self._projector = projector
        self._products = products
        self._raster_sources = raster_sources
        self._raster_patches = raster_patches
        self._exact_refinement = ExactRasterRefinementPlanner(
            projector=projector,
            raster_sources=raster_sources,
            refinement=refinement,
        )
        self._tile_manager_provider = tile_manager_provider
        self._viewport = viewport

    @property
    def _tile_manager(self) -> TileManager:
        """Return the presenter's current authoritative tile manager."""
        return self._tile_manager_provider()

    def apply_config(self, config: Config) -> None:
        """Apply viewport reconstruction policy to exact raster products."""
        self._exact_refinement.set_reconstruction_space(
            config.viewport_reconstruction_space
        )

    def build_frame_items(
        self,
        compiled: CompiledRenderScene,
        frame: RenderFrameGeometry,
        *,
        layers: tuple[CompiledRenderLayer, ...] | None = None,
        allow_exact: bool = True,
    ) -> tuple[RasterLayerRenderItem | SampledLayerRenderItem, ...]:
        """Build ordered raster primitives for one viewport frame."""
        planned_layers = compiled.layers if layers is None else layers
        results = tuple(
            result
            for layer in planned_layers
            for result in self._build_layer_items(
                compiled=compiled,
                layer=layer,
                frame=frame,
                allow_exact=allow_exact,
            )
        )
        if not exact_frame_is_ready(results):
            results = tuple(
                result
                for layer in planned_layers
                for result in self._build_layer_items(
                    compiled=compiled,
                    layer=layer,
                    frame=frame,
                    allow_exact=False,
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
        """Return tile-worker geometry only for a dense raster product."""
        if self._source_patches(compiled, layer, frame) is not None:
            return ()
        geometry = self._layer_geometry(
            compiled=compiled,
            layer=layer,
            frame=frame,
            qpane_rect=qpane_rect,
        )
        return () if geometry is None else (geometry,)

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
        source_product: RasterSourceProduct,
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
        allow_exact: bool,
    ) -> RasterPlanningResult | None:
        """Build one raster primitive and its requested tile identities."""
        source_product = self._source_image(compiled, layer, frame)
        if source_product is None:
            return None
        return self._build_product_item(
            compiled=compiled,
            layer=layer,
            frame=frame,
            source_product=source_product,
            allow_exact=allow_exact,
        )

    def _build_layer_items(
        self,
        *,
        compiled: CompiledRenderScene,
        layer: CompiledRenderLayer,
        frame: RenderFrameGeometry,
        allow_exact: bool,
    ) -> tuple[RasterPlanningResult, ...]:
        """Build one dense item or one globally sampled sparse-patch batch."""
        patches = self._source_patches(compiled, layer, frame)
        if patches is None:
            result = self._build_item(
                compiled=compiled,
                layer=layer,
                frame=frame,
                allow_exact=allow_exact,
            )
            return () if result is None else (result,)
        result = self._build_patch_item(
            compiled=compiled,
            layer=layer,
            frame=frame,
            patches=patches,
        )
        return () if result is None else (result,)

    def _build_patch_item(
        self,
        *,
        compiled: CompiledRenderScene,
        layer: CompiledRenderLayer,
        frame: RenderFrameGeometry,
        patches: tuple[RasterSourcePatch, ...],
    ) -> RasterPlanningResult | None:
        """Build visible sparse patches on one logical source sampling lattice."""
        if not patches:
            return None
        transform = self._projector.layer_to_panel(
            scene=compiled.scene,
            layer=layer.descriptor,
            source_size=layer.source_size,
            frame=frame,
        )
        lattice = (
            sampled_source_lattice(
                descriptor=layer.descriptor,
                source_size=layer.source_size,
                source_to_panel=transform,
                panel_rect=frame.sampling_panel_rect,
            )
            if source_sampling_phase_is_fractional(
                transform,
                frame.device_pixel_ratio,
            )
            else None
        )
        resolved_patches: list[tuple[RasterSourcePatch, RasterSourceProduct]] = []
        for patch in patches:
            source_product = self._patch_product(layer, patch, frame)
            if source_product is not None and patch.sample_bounds is not None:
                resolved_patches.append((patch, source_product))
        atlas_tile = self._native_patch_atlas(
            layer,
            tuple(resolved_patches),
            atlas_bounds=None if lattice is None else lattice.local_bounds,
        )
        if atlas_tile is not None:
            return RasterPlanningResult(
                item=SampledLayerRenderItem(
                    descriptor=layer.descriptor,
                    transform=transform,
                    placement=layer.descriptor.placement,
                    clip=layer.descriptor.clip,
                    source_size=layer.source_size,
                    presentation_sampling=raster_presentation_sampling(
                        transform,
                        frame.device_pixel_ratio,
                    ),
                    tiles=(atlas_tile,),
                    source_bounds=atlas_tile.source_rect,
                ),
                visible_tile_keys=frozenset(),
            )
        tiles: list[SampledTileRenderData] = []
        source_bounds: QRectF | None = None
        for patch, source_product in resolved_patches:
            sample_bounds = patch.sample_bounds
            if sample_bounds is None:
                continue
            sample_rect = self._patch_source_rect(layer, sample_bounds)
            core_rect = self._patch_source_rect(layer, patch.bounds)
            tiles.append(
                SampledTileRenderData(
                    source_product.image,
                    sample_rect,
                    QRectF(source_product.image.rect()),
                    core_rect if patch.bounds != sample_bounds else None,
                )
            )
            source_bounds = (
                QRectF(core_rect)
                if source_bounds is None
                else source_bounds.united(core_rect)
            )
        if not tiles:
            return None
        return RasterPlanningResult(
            item=SampledLayerRenderItem(
                descriptor=layer.descriptor,
                transform=transform,
                placement=layer.descriptor.placement,
                clip=layer.descriptor.clip,
                source_size=layer.source_size,
                presentation_sampling=raster_presentation_sampling(
                    transform,
                    frame.device_pixel_ratio,
                ),
                tiles=tuple(tiles),
                source_bounds=source_bounds,
            ),
            visible_tile_keys=frozenset(),
        )

    def _native_patch_atlas(
        self,
        layer: CompiledRenderLayer,
        patches: tuple[tuple[RasterSourcePatch, RasterSourceProduct], ...],
        *,
        atlas_bounds: RasterBounds | None,
    ) -> SampledTileRenderData | None:
        """Return one cached native atlas when sparse spacing remains bounded."""
        if not patches or any(
            product.scale != 1.0 or product.image.size() != patch.image.size()
            for patch, product in patches
        ):
            return None
        resolved_atlas_bounds = (
            patches[0][0].bounds if atlas_bounds is None else atlas_bounds
        )
        core_pixels = 0
        for patch, _product in patches:
            if atlas_bounds is None:
                resolved_atlas_bounds = resolved_atlas_bounds.united(patch.bounds)
            core_pixels += patch.bounds.width * patch.bounds.height
        atlas_pixels = resolved_atlas_bounds.width * resolved_atlas_bounds.height
        if (
            atlas_pixels > _MAX_SPARSE_ATLAS_PIXELS
            or atlas_pixels > core_pixels * _MAX_SPARSE_ATLAS_EXPANSION
        ):
            return None
        atlas_id = uuid.uuid5(
            layer.pyramid_asset_key.source_id,
            "atlas:"
            + ":".join(
                f"{patch.bounds.x},{patch.bounds.y},{patch.bounds.width},{patch.bounds.height}"
                for patch, _product in patches
            )
            + f":{resolved_atlas_bounds.x},{resolved_atlas_bounds.y},"
            f"{resolved_atlas_bounds.width},{resolved_atlas_bounds.height}",
        )
        atlas_key = source_render_asset_key(
            source_id=atlas_id,
            source_kind=f"{layer.pyramid_asset_key.source_kind}-patch-atlas",
            revision=layer.pyramid_asset_key.source_revision,
            source_path=layer.pyramid_asset_key.source_path,
        )
        atlas = self._products.sampled_image(
            asset_key=atlas_key,
            source_width=resolved_atlas_bounds.width,
            target_width=float(resolved_atlas_bounds.width),
            producer=lambda _scale: _compose_patch_atlas(
                resolved_atlas_bounds,
                patches,
            ),
        )
        if atlas is None or atlas.isNull():
            return None
        atlas_rect = self._patch_source_rect(layer, resolved_atlas_bounds)
        image_rect = QRectF(atlas.rect())
        integer_origin_sampling = (
            atlas_rect.size() == image_rect.size()
            and isclose(atlas_rect.x(), round(atlas_rect.x()))
            and isclose(atlas_rect.y(), round(atlas_rect.y()))
        )
        return SampledTileRenderData(
            atlas,
            atlas_rect,
            image_rect,
            integer_origin_sampling=integer_origin_sampling,
        )

    @staticmethod
    def _patch_source_rect(
        layer: CompiledRenderLayer,
        bounds: RasterBounds,
    ) -> QRectF:
        """Map source-local patch bounds into the logical raster product."""
        raster_bounds = layer.descriptor.raster_bounds
        if raster_bounds is None:
            return _rectf(bounds)
        scale_x = layer.source_size.width() / raster_bounds.width
        scale_y = layer.source_size.height() / raster_bounds.height
        return QRectF(
            (bounds.x - raster_bounds.x) * scale_x,
            (bounds.y - raster_bounds.y) * scale_y,
            bounds.width * scale_x,
            bounds.height * scale_y,
        )

    def _build_product_item(
        self,
        *,
        compiled: CompiledRenderScene,
        layer: CompiledRenderLayer,
        frame: RenderFrameGeometry,
        source_product: RasterSourceProduct,
        allow_exact: bool,
    ) -> RasterPlanningResult | None:
        """Build the sole raster primitive from one resolved source product."""
        exact = (
            self._exact_refinement.plan(
                compiled=compiled,
                layer=layer,
                frame=frame,
            )
            if allow_exact
            else None
        )
        if exact is not None and exact.item is not None:
            return RasterPlanningResult(
                item=exact.item,
                visible_tile_keys=frozenset(),
                exact_eligible=True,
                exact_ready=True,
            )
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
        device_pixel_ratio = frame.device_pixel_ratio
        relative_base_raster_scale = max(frame.zoom, 0.0) / max(
            frame.native_zoom,
            1e-9,
        )
        presentation_sampling = (
            raster_presentation_sampling_for_source_scale(relative_base_raster_scale)
            if layer.is_base_raster
            else raster_presentation_sampling(transform, device_pixel_ratio)
        )
        phase_stable_item = self._phase_stable_dense_item(
            layer=layer,
            frame=frame,
            source_product=source_product,
            transform=transform,
            presentation_sampling=presentation_sampling,
        )
        if phase_stable_item is not None:
            return RasterPlanningResult(
                item=phase_stable_item,
                visible_tile_keys=frozenset(),
                exact_eligible=bool(exact is not None and exact.eligible),
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
        return RasterPlanningResult(
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
                presentation_sampling=presentation_sampling,
                debug_draw_tile_grid=frame.debug_draw_tile_grid,
                tiles_to_draw=tile_plan.tiles_to_draw,
                tile_size=frame.tile_size,
                tile_overlap=frame.tile_overlap,
                max_tile_cols=tile_plan.max_tile_cols,
                max_tile_rows=tile_plan.max_tile_rows,
                visible_tile_range=tile_plan.visible_tile_range,
                is_base_raster=layer.is_base_raster,
            ),
            visible_tile_keys=tile_plan.visible_keys,
            exact_eligible=bool(exact is not None and exact.eligible),
        )

    def _phase_stable_dense_item(
        self,
        *,
        layer: CompiledRenderLayer,
        frame: RenderFrameGeometry,
        source_product: RasterSourceProduct,
        transform: PanelLayerMapping,
        presentation_sampling: RasterPresentationSampling,
    ) -> SampledLayerRenderItem | None:
        """Present patch-capable dense overlays on the shared source lattice."""
        source_image = source_product.image
        if (
            layer.presentation is not RasterPresentation.OVERLAY
            or self._raster_patches.owner_for(layer.descriptor.source) is None
            or source_product.scale != 1.0
            or source_image.size() != layer.source_size
            or not source_sampling_phase_is_fractional(
                transform,
                frame.device_pixel_ratio,
            )
        ):
            return None
        lattice = sampled_source_lattice(
            descriptor=layer.descriptor,
            source_size=layer.source_size,
            source_to_panel=transform,
            panel_rect=frame.sampling_panel_rect,
        )
        if lattice is None:
            return None
        return SampledLayerRenderItem(
            descriptor=layer.descriptor,
            transform=transform,
            placement=layer.descriptor.placement,
            clip=layer.descriptor.clip,
            source_size=layer.source_size,
            presentation_sampling=presentation_sampling,
            tiles=(
                SampledTileRenderData(
                    source_image,
                    lattice.source_rect,
                    lattice.source_rect,
                ),
            ),
            source_bounds=lattice.source_rect,
        )

    def _source_patches(
        self,
        compiled: CompiledRenderScene,
        layer: CompiledRenderLayer,
        frame: RenderFrameGeometry,
    ) -> tuple[RasterSourcePatch, ...] | None:
        """Return visible sparse products or request the dense fallback."""
        owner = self._raster_patches.owner_for(layer.descriptor.source)
        local_bounds = self._visible_local_bounds(compiled, layer, frame)
        if owner is None:
            return None
        if local_bounds is None:
            return ()
        patches = owner.source_patches(layer.descriptor.source, local_bounds)
        if patches is None:
            return None
        return tuple(
            sorted(
                (
                    patch
                    for patch in patches
                    if not patch.image.isNull() and patch.sample_bounds is not None
                ),
                key=lambda patch: (
                    patch.bounds.y,
                    patch.bounds.x,
                    patch.bounds.height,
                    patch.bounds.width,
                ),
            )
        )

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
        if transform is None or raster_bounds is None:
            return None
        return visible_scene_raster_bounds(
            transform,
            compiled.scene.bounds,
            frame.visible_scene_rect,
            raster_bounds,
        )

    def _patch_product(
        self,
        layer: CompiledRenderLayer,
        patch: RasterSourcePatch,
        frame: RenderFrameGeometry,
    ) -> RasterSourceProduct | None:
        """Select shared LOD for one sparse patch through the common product store."""
        image = patch.image
        if image.isNull():
            return None
        policy = self._raster_sources.product_policy(layer.descriptor.source)
        if policy is RasterProductPolicy.VOLATILE:
            return RasterSourceProduct(image=image, scale=1.0, cacheable=False)
        sample_bounds = patch.sample_bounds
        layer_transform = layer.descriptor.transform
        if sample_bounds is None or layer_transform is None:
            return None
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
        patch_placement = layer_transform.map_bounds(sample_bounds)
        selected = self._products.best_fit_image(
            asset_key=product_key,
            full_image=image,
            target_width=patch_placement.width * frame.zoom,
        )
        scale = selected.width() / image.width() if image.width() > 0 else 1.0
        return RasterSourceProduct(image=selected, scale=scale, cacheable=True)

    def _source_image(
        self,
        compiled: CompiledRenderScene,
        layer: CompiledRenderLayer,
        frame: RenderFrameGeometry,
    ) -> RasterSourceProduct | None:
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
            scale_bucket(
                layer_to_panel,
                frame.device_pixel_ratio,
                layer.source_size,
            ),
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
        return RasterSourceProduct(
            image=source_image,
            scale=pyramid_scale,
            cacheable=True,
        )

    @staticmethod
    def _direct_product(
        image: QImage | None,
        source_size: QSize,
    ) -> RasterSourceProduct | None:
        """Return one uncached sampled product with its authoritative scale."""
        if image is None or image.isNull():
            return None
        pyramid_scale = (
            image.width() / source_size.width() if source_size.width() > 0 else 1.0
        )
        return RasterSourceProduct(
            image=image,
            scale=pyramid_scale,
            cacheable=False,
        )

    def _render_strategy(
        self,
        layer: CompiledRenderLayer,
        frame: RenderFrameGeometry,
        source_product: RasterSourceProduct,
    ) -> RenderStrategy:
        """Return the direct or tiled strategy for a layer in one frame."""
        if not source_product.cacheable or not self._tile_manager.can_retain_tile(
            source_product.image
        ):
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
    ) -> PanelLayerMapping:
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
        transform: PanelLayerMapping,
        strategy: RenderStrategy,
    ) -> RasterTilePlan:
        """Return tile payloads and visible identities for one raster layer."""
        if strategy == RenderStrategy.DIRECT:
            return RasterTilePlan((), frozenset(), 0, 0, None)
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
        return RasterTilePlan(
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
        transform: PanelLayerMapping,
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


def _rectf(bounds: RasterBounds) -> QRectF:
    """Return floating source geometry for integer raster bounds."""
    return QRectF(
        float(bounds.x),
        float(bounds.y),
        float(bounds.width),
        float(bounds.height),
    )


def _compose_patch_atlas(
    atlas_bounds: RasterBounds,
    patches: tuple[tuple[RasterSourcePatch, RasterSourceProduct], ...],
) -> QImage:
    """Combine sparse native cores into one transparent source-local image."""
    atlas = QImage(
        atlas_bounds.width,
        atlas_bounds.height,
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    atlas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(atlas)
    painter.setCompositionMode(QPainter.CompositionMode_Source)
    try:
        for patch, product in patches:
            sample_bounds = patch.sample_bounds
            if sample_bounds is None:
                continue
            destination = QRectF(
                float(patch.bounds.x - atlas_bounds.x),
                float(patch.bounds.y - atlas_bounds.y),
                float(patch.bounds.width),
                float(patch.bounds.height),
            )
            source = QRectF(
                float(patch.bounds.x - sample_bounds.x),
                float(patch.bounds.y - sample_bounds.y),
                float(patch.bounds.width),
                float(patch.bounds.height),
            )
            painter.drawImage(destination, product.image, source)
    finally:
        painter.end()
    return atlas
