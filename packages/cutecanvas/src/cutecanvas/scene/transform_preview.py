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
    """Own and apply one transient layer transform without source mutation."""

    def __init__(
        self,
        resolve_clip: TransformPreviewClipResolver | None = None,
    ) -> None:
        """Initialize with an optional source-owned presentation-clip policy."""
        self._preview: LayerTransformPreview | None = None
        self._revision = 0
        self._resolve_clip = resolve_clip or _preserve_clip

    @property
    def current(self) -> LayerTransformPreview | None:
        """Return the active transient transform override."""
        return self._preview

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
        preview = LayerTransformPreview(scene_id, layer_id, transform)
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
        """Return scene with the matching transform and derived placement."""
        preview = self._preview
        if preview is None or preview.scene_id != scene.scene_id:
            return scene
        changed = False
        layers = []
        for layer in scene.layers:
            if layer.layer_id != preview.layer_id or layer.raster_bounds is None:
                layers.append(layer)
                continue
            placement = preview.transform.map_bounds(layer.raster_bounds)
            layers.append(
                replace(
                    layer,
                    placement=placement,
                    transform=preview.transform,
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
