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

"""Plan atomic exact settled products for immutable raster layers."""

from __future__ import annotations

import uuid
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage

from ..ferrastra import FerrastraRasterTileSource
from ..ferrastra.reconstruction import RasterReconstructionSpace
from ..scene.identity import SourceRenderAssetKey
from ..scene.raster_sampling import RasterPresentationSampling
from ..scene.render_plan import SampledLayerRenderItem, SampledTileRenderData
from ..scene.source_capabilities import (
    RasterPresentation,
    RasterPresentationRegistry,
    RasterProductPolicy,
)
from .compiled_scene import CompiledRenderLayer, CompiledRenderScene
from .frame_geometry import RenderFrameGeometry
from .frame_projector import SceneFrameProjector
from .panel_mapping import PiecewisePanelMapping
from .raster_sampling import exact_raster_sampling
from .render_sampling_grid import AffineSamplingGrid
from .render_tiles import RenderTileWorkCoordinator

_SOURCE_BUDGET_BYTES = 128 * 1024 * 1024
_SCENE_POLICY_LIMIT = 256


class _ExactAdoptionState(Protocol):
    """Expose the frame-level exact readiness fields used for adoption."""

    exact_eligible: bool
    exact_ready: bool


@dataclass(frozen=True, slots=True)
class ExactRasterRefinement:
    """Report exact eligibility and an optional complete presentation item."""

    eligible: bool
    item: SampledLayerRenderItem | None = None


class ExactRasterRefinementPlanner:
    """Request exact native pixels while immediate preview policy remains outside."""

    def __init__(
        self,
        *,
        projector: SceneFrameProjector,
        raster_sources: RasterPresentationRegistry,
        refinement: RenderTileWorkCoordinator,
    ) -> None:
        """Bind source adaptation, viewport projection, and sampled work policy."""
        self._projector = projector
        self._raster_sources = raster_sources
        self._refinement = refinement
        self._sources: OrderedDict[
            SourceRenderAssetKey,
            tuple[int, FerrastraRasterTileSource],
        ] = OrderedDict()
        self._source_bytes = 0
        self._reconstruction_space = RasterReconstructionSpace.SRGB_ENCODED
        self._presentation_managed_scenes: OrderedDict[uuid.UUID, None] = OrderedDict()

    def plan(
        self,
        *,
        compiled: CompiledRenderScene,
        layer: CompiledRenderLayer,
        frame: RenderFrameGeometry,
    ) -> ExactRasterRefinement:
        """Report an exact item or pending eligibility for frame-atomic adoption."""
        if compiled.hybrid_layers or any(
            candidate.presentation is RasterPresentation.OVERLAY
            for candidate in (*compiled.layers, *compiled.hybrid_fallback_layers)
        ):
            self._presentation_managed_scenes[compiled.scene.scene_id] = None
            self._presentation_managed_scenes.move_to_end(compiled.scene.scene_id)
            while len(self._presentation_managed_scenes) > _SCENE_POLICY_LIMIT:
                self._presentation_managed_scenes.popitem(last=False)
        if compiled.scene.scene_id in self._presentation_managed_scenes:
            return ExactRasterRefinement(False)
        if layer.presentation is not RasterPresentation.IMAGE:
            return ExactRasterRefinement(False)
        if (
            self._raster_sources.product_policy(layer.descriptor.source)
            is RasterProductPolicy.VOLATILE
        ):
            return ExactRasterRefinement(False)
        image = self._raster_sources.source_image(layer.descriptor.source)
        if image is None or image.isNull() or image.size() != layer.source_size:
            return ExactRasterRefinement(False)
        source_to_panel = self._projector.layer_to_panel(
            scene=compiled.scene,
            layer=layer.descriptor,
            source_size=layer.source_size,
            frame=frame,
        )
        if isinstance(source_to_panel, PiecewisePanelMapping):
            return ExactRasterRefinement(False)
        source_native_scale = (
            max(frame.zoom, 0.0) / max(frame.native_zoom, 1e-9)
            if layer.is_base_raster
            else None
        )
        sampling = exact_raster_sampling(
            source_to_panel,
            frame.device_pixel_ratio,
            source_native_scale=source_native_scale,
        )
        source = self._source(image, layer.pyramid_asset_key)
        refinement = self._refinement.request(
            source=source,
            source_to_panel=source_to_panel,
            panel_rect=frame.sampling_panel_rect,
            device_pixel_ratio=frame.device_pixel_ratio,
            exact_physical_grid=True,
            exact_sampling=sampling,
            reconstruction_space=self._reconstruction_space,
        )
        if not refinement.exact or refinement.products is None:
            return ExactRasterRefinement(True)
        tiles = tuple(
            SampledTileRenderData(
                product.image,
                product.source_rect,
                product.image_source_rect,
                product.source_clip_rect,
                exact_sampling=product.key.exact_sampling,
            )
            for product in refinement.products
        )
        panel_space_products = bool(
            refinement.products
            and isinstance(
                refinement.products[0].key.sampling_grid,
                AffineSamplingGrid,
            )
        )
        return ExactRasterRefinement(
            True,
            SampledLayerRenderItem(
                descriptor=layer.descriptor,
                transform=source_to_panel,
                placement=layer.descriptor.placement,
                clip=layer.descriptor.clip,
                source_size=layer.source_size,
                presentation_sampling=RasterPresentationSampling.NEAREST,
                tiles=tiles,
                source_bounds=QRectF(0.0, 0.0, image.width(), image.height()),
                panel_space_products=panel_space_products,
            ),
        )

    def set_reconstruction_space(
        self,
        reconstruction_space: RasterReconstructionSpace,
    ) -> None:
        """Select the working-space identity for subsequent exact products."""
        self._reconstruction_space = reconstruction_space

    def _source(
        self,
        image: QImage,
        asset_key: SourceRenderAssetKey,
    ) -> FerrastraRasterTileSource:
        """Return a bounded reusable native adapter for one source revision."""
        cached = self._sources.pop(asset_key, None)
        if cached is not None:
            self._sources[asset_key] = cached
            return cached[1]
        source = FerrastraRasterTileSource(image, asset_key)
        retained_bytes = int(image.sizeInBytes())
        self._sources[asset_key] = retained_bytes, source
        self._source_bytes += retained_bytes
        while len(self._sources) > 1 and self._source_bytes > _SOURCE_BUDGET_BYTES:
            _key, (evicted_bytes, _source) = self._sources.popitem(last=False)
            self._source_bytes -= evicted_bytes
        return source


def exact_frame_is_ready(results: Sequence[_ExactAdoptionState]) -> bool:
    """Return whether exact-eligible layers can be adopted as one complete frame."""
    eligible = tuple(result for result in results if result.exact_eligible)
    return not eligible or all(result.exact_ready for result in eligible)


__all__ = [
    "ExactRasterRefinement",
    "ExactRasterRefinementPlanner",
    "exact_frame_is_ready",
]
