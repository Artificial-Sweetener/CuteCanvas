#    CuteCanvas - High-performance layered image editor
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
"""Compile whole-layer coverage previews through the shared raster pipeline."""

from __future__ import annotations

import uuid

from qpane.sdk.scene import (
    RasterLayerRenderItem,
    SampledLayerRenderItem,
    SceneRenderItem,
    TransientRasterContribution,
)

from ..scene.layer_edge_preview import LayerEdgePreviewStore
from ..scene.pixel_fragments import RasterPixelFormat
from ..scene.source_capabilities import PixelPresentationRegistry
from .raster_transitions import RasterTransitionRenderCompiler


class LayerEdgePreviewRenderCompiler:
    """Present the current coverage edit without changing durable content."""

    def __init__(
        self,
        presentations: PixelPresentationRegistry,
        previews: LayerEdgePreviewStore,
    ) -> None:
        """Bind the shared source presenter and preview owner."""
        self._previews = previews
        self._transitions = RasterTransitionRenderCompiler(presentations)

    def target(self) -> tuple[uuid.UUID, uuid.UUID] | None:
        """Return the layer currently carrying a whole-layer preview."""
        preview = self._previews.current
        return None if preview is None else (preview.scene_id, preview.layer_id)

    def compile(
        self,
        render_items: tuple[SceneRenderItem, ...],
    ) -> TransientRasterContribution | None:
        """Compile current coverage through its layer's presentation owner."""
        preview = self._previews.current
        if preview is None:
            return None
        item = next(
            (
                candidate
                for candidate in render_items
                if isinstance(
                    candidate,
                    (RasterLayerRenderItem, SampledLayerRenderItem),
                )
                and candidate.descriptor.scene_id == preview.scene_id
                and candidate.descriptor.layer_id == preview.layer_id
            ),
            None,
        )
        if item is None:
            return None
        return self._transitions.compile(
            session_id=preview.session_id,
            scene_id=preview.scene_id,
            layer_id=preview.layer_id,
            pixel_format=RasterPixelFormat.COVERAGE8,
            transition=preview.transition,
            generation=preview.generation,
            item=item,
            retain_until_durable=False,
        )


__all__ = ["LayerEdgePreviewRenderCompiler"]
