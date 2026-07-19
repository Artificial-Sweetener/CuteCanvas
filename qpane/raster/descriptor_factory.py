#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Editable-raster descriptor factory for ordered scene assembly."""

from __future__ import annotations

from dataclasses import dataclass

from ..composition.layers import CompositionLayerInstance, CompositionLayerSourceKind
from ..scene.model import (
    BlendMode,
    LayerContentCapabilities,
    LayerDescriptor,
    LayerHitTest,
    LayerKind,
    SceneDescriptor,
)
from ..scene.sources import EditableRasterSource
from .assets import EditableRasterAssetStore


@dataclass(frozen=True, slots=True)
class EditableRasterLayerDescriptorFactory:
    """Resolve editable raster instances without owning composition order."""

    assets: EditableRasterAssetStore
    source_kind = CompositionLayerSourceKind.RASTER

    def revision(self) -> object:
        """Return per-asset revisions through stable on-demand descriptors."""
        return id(self.assets)

    def descriptor(
        self,
        scene: SceneDescriptor,
        instance: CompositionLayerInstance,
    ) -> LayerDescriptor | None:
        """Resolve one editable raster composition instance."""
        asset = self.assets.get(instance.source_id)
        if asset is None:
            return None
        surface = asset.surface
        bounds = surface.bounds
        content_revision, _structure_revision = surface.revisions()
        return LayerDescriptor(
            scene_id=scene.scene_id,
            layer_id=instance.layer_id,
            kind=LayerKind.RASTER,
            source=EditableRasterSource(asset.raster_id, content_revision),
            placement=instance.transform.map_bounds(bounds),
            visible=instance.visible,
            opacity=instance.opacity,
            blend_mode=BlendMode.NORMAL,
            clip=None,
            hit_test=LayerHitTest(enabled=instance.hit_test, role=instance.role),
            interaction=instance.interaction,
            capabilities=LayerContentCapabilities(raster_editable=True),
            source_revision=content_revision,
            raster_bounds=bounds,
            transform=instance.transform,
        )
