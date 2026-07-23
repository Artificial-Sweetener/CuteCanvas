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
"""Editable-raster descriptor factory for ordered scene assembly."""

from __future__ import annotations

from dataclasses import dataclass

from qpane.sdk.scene import (
    BlendMode,
    LayerContentCapabilities,
    LayerDescriptor,
    LayerHitTest,
    LayerKind,
    SceneDescriptor,
)

from ..composition.layers import CompositionLayerInstance
from .assets import EditableRasterAssetStore
from .source_reference import EditableRasterReference


@dataclass(frozen=True, slots=True)
class EditableRasterLayerDescriptorFactory:
    """Resolve editable raster instances without owning composition order."""

    assets: EditableRasterAssetStore
    source_type = EditableRasterReference

    def revision(self) -> object:
        """Return per-asset revisions through stable on-demand descriptors."""
        return self.assets.revision

    def descriptor(
        self,
        scene: SceneDescriptor,
        instance: CompositionLayerInstance,
    ) -> LayerDescriptor | None:
        """Resolve one editable raster composition instance."""
        if not isinstance(instance.source, EditableRasterReference):
            return None
        asset = self.assets.get(instance.source.raster_id)
        if asset is None:
            return None
        surface = asset.surface
        bounds = surface.bounds
        content_revision, _structure_revision = surface.revisions()
        return LayerDescriptor(
            scene_id=scene.scene_id,
            layer_id=instance.layer_id,
            kind=LayerKind.RASTER,
            source=instance.source,
            placement=instance.transform.map_bounds(bounds),
            visible=instance.visible,
            opacity=instance.opacity,
            blend_mode=BlendMode.NORMAL,
            clip=instance.clip,
            effects=instance.effects,
            hit_test=LayerHitTest(enabled=instance.hit_test, role=instance.role),
            interaction=instance.interaction,
            capabilities=LayerContentCapabilities(raster_editable=True),
            source_revision=content_revision,
            raster_bounds=bounds,
            transform=instance.transform,
        )
