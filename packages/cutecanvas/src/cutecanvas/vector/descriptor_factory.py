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
"""Scene descriptor adaptation for composition-owned vector instances."""

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
from .projection import VectorDocumentProjection
from .source_reference import VectorDocumentReference


@dataclass(frozen=True, slots=True)
class VectorLayerDescriptorFactory:
    """Resolve vector instances without owning composition order."""

    projection: VectorDocumentProjection
    source_type = VectorDocumentReference

    def revision(self) -> object:
        """Return the aggregate document revision for scene invalidation."""
        return self.projection.revision

    def descriptor(
        self,
        scene: SceneDescriptor,
        instance: CompositionLayerInstance,
    ) -> LayerDescriptor | None:
        """Resolve one vector document instance."""
        if not isinstance(instance.source, VectorDocumentReference):
            return None
        snapshot = self.projection.snapshot(instance.source)
        if snapshot is None:
            return None
        document = snapshot.document
        return LayerDescriptor(
            scene_id=scene.scene_id,
            layer_id=instance.layer_id,
            kind=LayerKind.VECTOR,
            source=instance.source,
            placement=instance.transform.map_bounds(document.bounds),
            visible=instance.visible,
            opacity=instance.opacity,
            blend_mode=BlendMode.NORMAL,
            clip=instance.clip,
            effects=instance.effects,
            hit_test=LayerHitTest(enabled=instance.hit_test, role=instance.role),
            interaction=instance.interaction,
            capabilities=LayerContentCapabilities(vector_editable=True),
            source_revision=self.projection.source_revision,
            raster_bounds=document.bounds,
            transform=instance.transform,
        )
