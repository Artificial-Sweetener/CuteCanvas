#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Scene descriptors for non-destructive placed raster sources."""

from dataclasses import dataclass

from ..composition.layers import CompositionLayerInstance
from ..scene.model import (
    BlendMode,
    LayerContentCapabilities,
    LayerDescriptor,
    LayerHitTest,
    LayerKind,
    SceneDescriptor,
)
from ..scene.raster import RasterBounds
from .source_reference import PlacedAssetReference
from .store import PlacedAssetStore


@dataclass(frozen=True, slots=True)
class PlacedAssetLayerDescriptorFactory:
    """Resolve placed instances without owning composition order or pixels."""

    assets: PlacedAssetStore
    source_type = PlacedAssetReference

    def revision(self) -> object:
        """Return the aggregate asset revision for compile invalidation."""
        return self.assets.revision

    def descriptor(
        self,
        scene: SceneDescriptor,
        instance: CompositionLayerInstance,
    ) -> LayerDescriptor | None:
        """Resolve one placed raster composition instance."""
        if not isinstance(instance.source, PlacedAssetReference):
            return None
        snapshot = self.assets.get(instance.source.asset_id)
        if snapshot is None:
            return None
        bounds = RasterBounds.from_size(snapshot.source_size)
        return LayerDescriptor(
            scene_id=scene.scene_id,
            layer_id=instance.layer_id,
            kind=LayerKind.IMAGE,
            source=instance.source,
            placement=instance.transform.map_bounds(bounds),
            visible=instance.visible,
            opacity=instance.opacity,
            blend_mode=BlendMode.NORMAL,
            clip=instance.clip,
            effects=instance.effects,
            hit_test=LayerHitTest(enabled=instance.hit_test, role=instance.role),
            interaction=instance.interaction,
            capabilities=LayerContentCapabilities(raster_editable=False),
            source_revision=snapshot.content_revision,
            raster_bounds=bounds,
            transform=instance.transform,
        )
