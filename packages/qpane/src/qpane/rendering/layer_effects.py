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
"""Compile composition layer effects into render-item-local geometry."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QSize

from ..scene.affine import LayerTransform
from ..scene.effects import LayerEffectRenderRegistry
from ..scene.model import LayerPlacement
from ..scene.render_plan import (
    RasterLayerRenderItem,
    SampledLayerRenderItem,
    SceneRenderItem,
    VectorLayerRenderItem,
)


class LayerEffectFrameCompiler:
    """Decorate source-neutral render items with derived effect geometry."""

    def __init__(self, effects: LayerEffectRenderRegistry) -> None:
        """Bind the open typed effect registry."""
        self._effects = effects

    def apply(self, items: tuple[SceneRenderItem, ...]) -> tuple[SceneRenderItem, ...]:
        """Return items with target-render-local intersected clip paths."""
        return tuple(self._apply_item(item) for item in items)

    def _apply_item(self, item: SceneRenderItem) -> SceneRenderItem:
        """Compile one descriptor's effects without branching on source kind."""
        descriptor = item.descriptor
        clip = self._effects.combined_clip(
            descriptor.effects,
            descriptor.raster_bounds,
        )
        if clip is None:
            return item
        source_size = _source_size(item)
        bounds = descriptor.raster_bounds
        if bounds is None or source_size.isEmpty():
            return replace(item, effect_clip_path=clip)
        local_to_render = LayerTransform.from_placement(
            bounds,
            LayerPlacement(
                0.0,
                0.0,
                float(source_size.width()),
                float(source_size.height()),
            ),
        )
        return replace(
            item,
            effect_clip_path=local_to_render.to_qtransform().map(clip),
        )


def _source_size(item: SceneRenderItem) -> QSize:
    """Return one render primitive's actual source coordinate dimensions."""
    if isinstance(item, RasterLayerRenderItem):
        return item.source_image.size()
    if isinstance(item, VectorLayerRenderItem):
        return QSize(item.source_size)
    if isinstance(item, SampledLayerRenderItem):
        return QSize(item.source_size)
    return QSize()
