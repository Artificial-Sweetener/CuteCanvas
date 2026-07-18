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

"""Transient scene-layer placement preview applied after scene assembly."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace

from .model import LayerPlacement, SceneDescriptor
from .raster import LayerTransform


@dataclass(frozen=True, slots=True)
class LayerPlacementPreview:
    """Describe one non-durable placement override for rendering."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    placement: LayerPlacement


class SceneLayerPlacementPreview:
    """Own and apply one transient placement override without source mutation."""

    def __init__(self) -> None:
        """Initialize without an active placement preview."""
        self._preview: LayerPlacementPreview | None = None
        self._revision = 0

    @property
    def current(self) -> LayerPlacementPreview | None:
        """Return the active transient placement override."""
        return self._preview

    def revision(self) -> int:
        """Return the revision used to invalidate compiled scene geometry."""
        return self._revision

    def set(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        placement: LayerPlacement,
    ) -> bool:
        """Set a transient placement override and report whether it changed."""
        preview = LayerPlacementPreview(scene_id, layer_id, placement)
        if preview == self._preview:
            return False
        self._preview = preview
        self._revision += 1
        return True

    def clear(self) -> bool:
        """Clear the transient override and report whether it changed."""
        if self._preview is None:
            return False
        self._preview = None
        self._revision += 1
        return True

    def process_scene(self, scene: SceneDescriptor) -> SceneDescriptor:
        """Return ``scene`` with the active matching placement overridden."""
        preview = self._preview
        if preview is None or preview.scene_id != scene.scene_id:
            return scene
        changed = False
        layers = []
        for layer in scene.layers:
            if layer.layer_id == preview.layer_id:
                transform = (
                    layer.transform
                    if layer.raster_bounds is None
                    else LayerTransform.from_placement(
                        layer.raster_bounds,
                        preview.placement,
                    )
                )
                layers.append(
                    replace(
                        layer,
                        placement=preview.placement,
                        transform=transform,
                    )
                )
                changed = True
            else:
                layers.append(layer)
        return replace(scene, layers=tuple(layers)) if changed else scene
