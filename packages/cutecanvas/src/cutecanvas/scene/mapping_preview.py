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

"""Transient source-neutral layer mappings applied after scene assembly."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace

from qpane.sdk.scene import (
    LayerClip,
    LayerDescriptor,
    LayerMapping,
    LayerPlacement,
    SceneDescriptor,
)

MappingPreviewClipResolver = Callable[
    [SceneDescriptor, LayerDescriptor, LayerPlacement], LayerClip | None
]


@dataclass(frozen=True, slots=True)
class LayerMappingPreview:
    """Describe one non-durable exact layer-mapping override for rendering."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    mapping: LayerMapping


class SceneLayerMappingPreview:
    """Own and apply one transient layer-mapping set without source mutation."""

    def __init__(
        self,
        resolve_clip: MappingPreviewClipResolver | None = None,
    ) -> None:
        """Initialize with an optional source-owned presentation-clip policy."""
        self._previews: tuple[LayerMappingPreview, ...] = ()
        self._revision = 0
        self._resolve_clip = resolve_clip or _preserve_clip

    @property
    def previews(self) -> tuple[LayerMappingPreview, ...]:
        """Return all active transient mapping overrides."""
        return self._previews

    def mapping_for(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> LayerMapping | None:
        """Return one active mapping override by identity."""
        preview = next(
            (
                candidate
                for candidate in self._previews
                if candidate.scene_id == scene_id and candidate.layer_id == layer_id
            ),
            None,
        )
        return None if preview is None else preview.mapping

    def revision(self) -> int:
        """Return the revision used to invalidate compiled instance geometry."""
        return self._revision

    def set(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        mapping: LayerMapping,
    ) -> bool:
        """Set a transient mapping override and report whether it changed."""
        return self.set_many((LayerMappingPreview(scene_id, layer_id, mapping),))

    def set_many(self, previews: tuple[LayerMappingPreview, ...]) -> bool:
        """Set one coherent transient mapping set."""
        identities = {(preview.scene_id, preview.layer_id) for preview in previews}
        if len(identities) != len(previews):
            raise ValueError("preview layer identities must be unique")
        if previews == self._previews:
            return False
        self._previews = previews
        self._revision += 1
        return True

    def clear(self) -> bool:
        """Clear the transient overrides and report whether they changed."""
        if not self._previews:
            return False
        self._previews = ()
        self._revision += 1
        return True

    def process_scene(self, scene: SceneDescriptor) -> SceneDescriptor:
        """Return a scene with matching mappings and derived placements."""
        mappings = {
            preview.layer_id: preview.mapping
            for preview in self._previews
            if preview.scene_id == scene.scene_id
        }
        if not mappings:
            return scene
        changed = False
        layers = []
        for layer in scene.layers:
            mapping = mappings.get(layer.layer_id)
            if mapping is None or layer.raster_bounds is None:
                layers.append(layer)
                continue
            placement = mapping.map_bounds(layer.raster_bounds)
            layers.append(
                replace(
                    layer,
                    placement=placement,
                    transform=mapping,
                    clip=self._resolve_clip(scene, layer, placement),
                )
            )
            changed = True
        return replace(scene, layers=tuple(layers)) if changed else scene


def _preserve_clip(
    _scene: SceneDescriptor,
    layer: LayerDescriptor,
    _placement: LayerPlacement,
) -> LayerClip | None:
    """Preserve descriptor clips when no source-specific policy is installed."""
    return layer.clip


__all__ = ["LayerMappingPreview", "SceneLayerMappingPreview"]
