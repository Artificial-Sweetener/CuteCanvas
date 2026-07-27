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
from dataclasses import dataclass

from PySide6.QtCore import QSize

from ..hybrid.tile_source import HybridRenderTileSource
from ..scene.model import LayerDescriptor
from ..scene.render_plan import SampledLayerRenderItem, SampledTileRenderData
from .compiled_scene import CompiledRenderScene
from .frame_geometry import RenderFrameGeometry
from .frame_projector import SceneFrameProjector
from .raster_sampling import (
    raster_sample_scale_limit,
    smooth_raster_sampling_enabled,
)
from .render_tile_types import RenderTileBatchSource
from .render_tiles import RenderTileWorkCoordinator
from .sdk import HybridSource


@dataclass(frozen=True, slots=True)
class SampledFramePlan:
    """Carry sampled items plus layers awaiting their first complete product."""

    items: tuple[SampledLayerRenderItem, ...]
    pending_layer_ids: frozenset[uuid.UUID] = frozenset()


class HybridRenderPlanner:
    """Compile visible hybrid documents into atomic sampled tile batches."""

    def __init__(
        self,
        *,
        projector: SceneFrameProjector,
        refinement: RenderTileWorkCoordinator,
    ) -> None:
        """Bind hybrid snapshots, frame projection, and shared refinement."""
        self._projector = projector
        self._refinement = refinement

    def build_frame_items(
        self,
        compiled: CompiledRenderScene,
        frame: RenderFrameGeometry,
    ) -> SampledFramePlan:
        """Return sampled primitives for every compiled hybrid layer."""
        items: list[SampledLayerRenderItem] = []
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
                continue
            refinement = self._refinement.request(
                source=HybridRenderTileSource(
                    document,
                    snapshot.style,
                    snapshot.presentation_revision,
                ),
                source_to_panel=layer_to_panel,
                panel_rect=frame.sampling_panel_rect,
                device_pixel_ratio=frame.device_pixel_ratio,
                maximum_scale=raster_sample_scale_limit(
                    layer_to_panel,
                    frame.device_pixel_ratio,
                ),
            )
            products = refinement.products
            if refinement.pending:
                pending_layer_ids.add(layer.layer_id)
            if products is None:
                continue
            items.append(
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
                )
            )
        for compiled_layer in compiled.sampled_layers:
            source = compiled_layer.snapshot
            if not isinstance(source, RenderTileBatchSource):
                continue
            item, pending = self._sampled_item(
                compiled, frame, compiled_layer.descriptor, source
            )
            if pending:
                pending_layer_ids.add(compiled_layer.descriptor.layer_id)
            if item is not None:
                items.append(item)
        return SampledFramePlan(tuple(items), frozenset(pending_layer_ids))

    def _sampled_item(
        self,
        compiled: CompiledRenderScene,
        frame: RenderFrameGeometry,
        layer: LayerDescriptor,
        source: RenderTileBatchSource,
    ) -> tuple[SampledLayerRenderItem | None, bool]:
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
            return None, refinement.pending
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
        )
