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

"""Apply composition-owned default image layer state to resolved scenes."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace

from ..scene.model import LayerHitTest, SceneDescriptor
from ..scene.sources import CatalogImageSource
from .layers import CompositionLayerInstance, CompositionLayerSourceKind


@dataclass(frozen=True, slots=True)
class ImageSceneLayerAdapter:
    """Apply authoritative default image instance state without feature coupling."""

    layer_instances: Callable[[uuid.UUID], tuple[CompositionLayerInstance, ...]]
    revision_provider: Callable[[], object]

    def revision(self) -> object:
        """Return the composition layer revision used by scene compilation."""
        return self.revision_provider()

    def adapt_base_scene(
        self,
        base_scene: SceneDescriptor,
        image_id: uuid.UUID | None,
    ) -> SceneDescriptor:
        """Apply catalog instance presentation, placement, and interaction policy."""
        if image_id is None:
            return base_scene
        instances = self.layer_instances(image_id)
        catalog_instances = {
            instance.source_id: instance
            for instance in instances
            if instance.source_kind == CompositionLayerSourceKind.CATALOG_IMAGE
        }
        changed = False
        layers = []
        for layer in base_scene.layers:
            source = layer.source
            instance = (
                catalog_instances.get(source.image_id)
                if isinstance(source, CatalogImageSource)
                else None
            )
            if instance is None:
                layers.append(layer)
                continue
            layers.append(
                replace(
                    layer,
                    placement=instance.placement,
                    visible=instance.visible,
                    opacity=instance.opacity,
                    hit_test=LayerHitTest(
                        enabled=instance.hit_test,
                        role=instance.role,
                    ),
                    interaction=instance.interaction,
                )
            )
            changed = True
        return replace(base_scene, layers=tuple(layers)) if changed else base_scene
