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

from PySide6.QtCore import QRectF, QSize

from ..hybrid.tile_source import HybridRenderTileSource
from ..scene.render_plan import SampledLayerRenderItem, SampledTileRenderData
from .compiled_scene import CompiledRenderScene
from .frame_geometry import RenderFrameGeometry
from .frame_projector import SceneFrameProjector
from .render_tiles import RenderTileWorkCoordinator
from .sdk import HybridSource


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
    ) -> tuple[SampledLayerRenderItem, ...]:
        """Return sampled primitives for every compiled hybrid layer."""
        items: list[SampledLayerRenderItem] = []
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
            refinement = self._refinement.request(
                source=HybridRenderTileSource(
                    document,
                    snapshot.style,
                    snapshot.presentation_revision,
                ),
                source_to_panel=layer_to_panel,
                panel_rect=QRectF(frame.qpane_rect),
                device_pixel_ratio=_device_pixel_ratio(frame),
            )
            products = refinement.products
            if products is None:
                continue
            items.append(
                SampledLayerRenderItem(
                    descriptor=layer,
                    transform=layer_to_panel,
                    placement=layer.placement,
                    clip=layer.clip,
                    source_size=source_size,
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
        return tuple(items)


def _device_pixel_ratio(frame: RenderFrameGeometry) -> float:
    """Derive physical/logical scale from detached frame geometry."""
    logical_width = frame.qpane_rect.width()
    if logical_width <= 0:
        return 1.0
    return max(0.01, frame.physical_viewport_rect.width() / logical_width)
