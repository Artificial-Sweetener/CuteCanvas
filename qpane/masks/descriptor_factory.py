#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Mask-domain scene descriptor factory for composition layer assembly."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

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
from .source_reference import MaskAssetReference


class MaskDescriptorAsset(Protocol):
    """Mask asset geometry required to assemble a descriptor."""

    @property
    def surface(self):
        """Return authoritative mask coverage storage."""
        ...


class MaskDescriptorAssets(Protocol):
    """Resolve mask assets for descriptor assembly."""

    def get_layer(self, mask_id: uuid.UUID) -> MaskDescriptorAsset | None:
        """Return one mask asset when present."""
        ...


class MaskDescriptorRenders(Protocol):
    """Provide render revisions for mask descriptors."""

    def render_revision(self, mask_id: uuid.UUID) -> int:
        """Return current derived-render revision."""
        ...


@dataclass(frozen=True, slots=True)
class MaskLayerDescriptorFactory:
    """Resolve mask composition instances without owning scene order."""

    assets: MaskDescriptorAssets
    renders: MaskDescriptorRenders
    dynamic_revision: Callable[[], object]
    source_type = MaskAssetReference

    def revision(self) -> object:
        """Return mask-domain state affecting descriptors."""
        return self.dynamic_revision()

    def descriptor(
        self,
        scene: SceneDescriptor,
        instance: CompositionLayerInstance,
    ) -> LayerDescriptor | None:
        """Resolve one mask instance into a complete scene descriptor."""
        if not isinstance(instance.source, MaskAssetReference):
            return None
        mask_id = instance.source.mask_id
        asset = self.assets.get_layer(mask_id)
        if asset is None or asset.surface.is_null():
            return None
        raster_bounds: RasterBounds | None = asset.surface.bounds
        if raster_bounds is None:
            return None
        revision = max(0, int(self.renders.render_revision(mask_id)))
        return LayerDescriptor(
            scene_id=scene.scene_id,
            layer_id=instance.layer_id,
            kind=LayerKind.MASK,
            source=instance.source,
            placement=instance.transform.map_bounds(raster_bounds),
            visible=instance.visible,
            opacity=instance.opacity,
            blend_mode=BlendMode.NORMAL,
            clip=instance.clip,
            effects=instance.effects,
            hit_test=LayerHitTest(enabled=instance.hit_test, role=instance.role),
            interaction=instance.interaction,
            capabilities=LayerContentCapabilities(
                raster_editable=True,
                coverage_source=True,
            ),
            source_revision=revision,
            raster_bounds=raster_bounds,
            transform=instance.transform,
        )
