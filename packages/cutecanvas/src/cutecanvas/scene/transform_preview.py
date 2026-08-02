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
"""Transient source-neutral layer transforms applied after scene assembly."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace

from qpane.sdk.scene import (
    LayerClip,
    LayerDescriptor,
    LayerPlacement,
    LayerTransform,
    SceneDescriptor,
)

TransformPreviewClipResolver = Callable[
    [SceneDescriptor, LayerDescriptor, LayerPlacement], LayerClip | None
]


@dataclass(frozen=True, slots=True)
class LayerTransformPreview:
    """Describe one non-durable exact transform override for rendering."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    transform: LayerTransform


class SceneLayerTransformPreview:
    """Own and apply one transient transform set without source mutation."""

    def __init__(
        self,
        resolve_clip: TransformPreviewClipResolver | None = None,
    ) -> None:
        """Initialize with an optional source-owned presentation-clip policy."""
        self._previews: tuple[LayerTransformPreview, ...] = ()
        self._revision = 0
        self._resolve_clip = resolve_clip or _preserve_clip

    @property
    def previews(self) -> tuple[LayerTransformPreview, ...]:
        """Return all active transient transform overrides."""
        return self._previews

    def transform_for(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> LayerTransform | None:
        """Return one active transform override by identity."""
        preview = next(
            (
                candidate
                for candidate in self._previews
                if candidate.scene_id == scene_id and candidate.layer_id == layer_id
            ),
            None,
        )
        return None if preview is None else preview.transform

    def revision(self) -> int:
        """Return the revision used to invalidate compiled instance geometry."""
        return self._revision

    def set(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        transform: LayerTransform,
    ) -> bool:
        """Set a transient transform override and report whether it changed."""
        return self.set_many((LayerTransformPreview(scene_id, layer_id, transform),))

    def set_many(self, previews: tuple[LayerTransformPreview, ...]) -> bool:
        """Set one coherent transient transform set."""
        identities = {(preview.scene_id, preview.layer_id) for preview in previews}
        if len(identities) != len(previews):
            raise ValueError("preview layer identities must be unique")
        if previews == self._previews:
            return False
        self._previews = previews
        self._revision += 1
        return True

    def clear(self) -> bool:
        """Clear the transient override and report whether it changed."""
        if not self._previews:
            return False
        self._previews = ()
        self._revision += 1
        return True

    def process_scene(self, scene: SceneDescriptor) -> SceneDescriptor:
        """Return scene with the matching transform and derived placement."""
        transforms = {
            preview.layer_id: preview.transform
            for preview in self._previews
            if preview.scene_id == scene.scene_id
        }
        if not transforms:
            return scene
        changed = False
        layers = []
        for layer in scene.layers:
            transform = transforms.get(layer.layer_id)
            if transform is None or layer.raster_bounds is None:
                layers.append(layer)
                continue
            placement = transform.map_bounds(layer.raster_bounds)
            layers.append(
                replace(
                    layer,
                    placement=placement,
                    transform=transform,
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
