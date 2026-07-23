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
"""Catalog-domain adaptation of composition instances into scene layers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from PySide6.QtGui import QImage
from qpane.sdk.catalog import CatalogImageReference
from qpane.sdk.scene import (
    BlendMode,
    LayerDescriptor,
    LayerHitTest,
    LayerKind,
    RasterBounds,
    SceneDescriptor,
)

from ..composition.layers import CompositionLayerInstance


class CatalogDescriptorSource(Protocol):
    """Catalog reads needed to resolve a composition layer descriptor."""

    def getImage(self, image_id: uuid.UUID) -> QImage | None:
        """Return pixels for one catalog resource."""
        ...

    def getRevision(self, image_id: uuid.UUID) -> int | None:
        """Return the current catalog resource revision."""
        ...


@dataclass(frozen=True, slots=True)
class CatalogLayerDescriptorFactory:
    """Resolve catalog resources into generic composition descriptors."""

    catalog: CatalogDescriptorSource
    source_type = CatalogImageReference

    def revision(self) -> object:
        """Return a stable revision because catalog revisions live on descriptors."""
        return self.source_type

    def descriptor(
        self,
        scene: SceneDescriptor,
        instance: CompositionLayerInstance,
    ) -> LayerDescriptor | None:
        """Resolve one catalog instance directly from its shared resource."""
        source = instance.source
        if not isinstance(source, CatalogImageReference):
            return None
        image = self.catalog.getImage(source.image_id)
        if image is None or image.isNull():
            return None
        bounds = RasterBounds.from_size(image.size())
        return LayerDescriptor(
            scene_id=scene.scene_id,
            layer_id=instance.layer_id,
            kind=LayerKind.IMAGE,
            source=source,
            placement=instance.transform.map_bounds(bounds),
            transform=instance.transform,
            visible=instance.visible,
            opacity=instance.opacity,
            blend_mode=BlendMode.NORMAL,
            clip=instance.clip,
            effects=instance.effects,
            hit_test=LayerHitTest(enabled=instance.hit_test, role=instance.role),
            interaction=instance.interaction,
            source_revision=max(
                0,
                int(self.catalog.getRevision(source.image_id) or 0),
            ),
            raster_bounds=bounds,
        )
