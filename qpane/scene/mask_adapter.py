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

"""Adapt composition-owned mask layer instances into internal scenes."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from ..composition.layers import (
    CompositionLayerInstance,
    CompositionLayerSourceKind,
)
from .model import (
    BlendMode,
    LayerDescriptor,
    LayerHitTest,
    LayerKind,
    LayerPlacement,
    SceneDescriptor,
)
from .sources import CatalogImageSource, MaskLayerSource


class MaskLayerLike(Protocol):
    """Mask asset fields required to resolve source geometry."""

    @property
    def mask_image(self):
        """Expose grayscale source pixels for placement."""
        ...


class MaskAssetLookup(Protocol):
    """Resolve mask assets without owning composition state."""

    def get_layer(self, mask_id: uuid.UUID) -> MaskLayerLike | None:
        """Return the mask asset for one identifier."""
        ...


class MaskRenderRevisionLookup(Protocol):
    """Provide source revisions for mask rendering."""

    def render_revision(self, mask_id: uuid.UUID) -> int:
        """Return the current render revision for one mask asset."""
        ...


@dataclass(frozen=True, slots=True)
class MaskCompositionSceneAdapter:
    """Insert mask assets according to composition-owned cross-kind z-order."""

    layer_instances: Callable[[uuid.UUID], tuple[CompositionLayerInstance, ...]]
    revision_provider: Callable[[], object]
    assets: MaskAssetLookup
    renders: MaskRenderRevisionLookup

    def revision(self) -> object:
        """Return the mask and composition scene revision."""
        return self.revision_provider()

    def adapt_base_scene(
        self,
        base_scene: SceneDescriptor,
        image_id: uuid.UUID | None,
    ) -> SceneDescriptor:
        """Return a complete image scene ordered by composition instances."""
        if image_id is None:
            return base_scene
        instances = self.layer_instances(image_id)
        if not instances:
            return base_scene
        base_by_source = {
            layer.source.image_id: layer
            for layer in base_scene.layers
            if isinstance(layer.source, CatalogImageSource)
        }
        layers: list[LayerDescriptor] = []
        for instance in instances:
            if instance.source_kind == CompositionLayerSourceKind.CATALOG_IMAGE:
                layer = base_by_source.get(instance.source_id)
            else:
                layer = self._mask_descriptor(base_scene, instance)
            if layer is not None:
                layers.append(layer)
        if not layers:
            return base_scene
        return SceneDescriptor(
            scene_id=base_scene.scene_id,
            kind=base_scene.kind,
            bounds=base_scene.bounds,
            layers=tuple(layers),
        )

    def _mask_descriptor(
        self,
        scene: SceneDescriptor,
        instance: CompositionLayerInstance,
    ) -> LayerDescriptor | None:
        """Resolve one composition mask instance into a scene descriptor."""
        asset = self.assets.get_layer(instance.source_id)
        if asset is None or asset.mask_image.isNull():
            return None
        revision = max(
            0,
            int(self.renders.render_revision(instance.source_id)),
        )
        return LayerDescriptor(
            scene_id=scene.scene_id,
            layer_id=instance.layer_id,
            kind=LayerKind.MASK,
            source=MaskLayerSource(mask_id=instance.source_id, revision=revision),
            placement=LayerPlacement(
                x=0.0,
                y=0.0,
                width=float(asset.mask_image.width()),
                height=float(asset.mask_image.height()),
            ),
            visible=instance.visible,
            opacity=instance.opacity,
            blend_mode=BlendMode.NORMAL,
            clip=None,
            hit_test=LayerHitTest(
                enabled=instance.hit_test,
                selectable=instance.selectable,
                role=instance.role,
            ),
            source_revision=revision,
        )
