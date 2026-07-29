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

"""Own transient layer clips independently from durable scene content."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import replace

from ..scene.model import LayerClip
from ..scene.render_plan import SceneRenderItem


class LayerClipPresentationRegistry:
    """Apply active-scene clip overrides without recompiling scene content."""

    def __init__(self) -> None:
        """Create an empty presentation override collection."""
        self._clips: dict[tuple[uuid.UUID, uuid.UUID], LayerClip] = {}

    def set(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        clip: LayerClip,
    ) -> bool:
        """Set one clip override and report whether presentation changed."""
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        if not isinstance(clip, LayerClip):
            raise TypeError("clip must be a LayerClip")
        key = (scene_id, layer_id)
        if self._clips.get(key) == clip:
            return False
        self._clips[key] = clip
        return True

    def reconcile(
        self,
        scene_id: uuid.UUID | None,
        layer_ids: Iterable[uuid.UUID] = (),
    ) -> None:
        """Discard overrides that cannot target the active scene snapshot."""
        valid_layers = frozenset(layer_ids)
        self._clips = {
            key: clip
            for key, clip in self._clips.items()
            if key[0] == scene_id and key[1] in valid_layers
        }

    def apply(
        self,
        scene_id: uuid.UUID,
        items: tuple[SceneRenderItem, ...],
    ) -> tuple[SceneRenderItem, ...]:
        """Return render items with current presentation clips projected."""
        if not self._clips:
            return items
        return tuple(self._apply_to_item(scene_id, item) for item in items)

    def _apply_to_item(
        self,
        scene_id: uuid.UUID,
        item: SceneRenderItem,
    ) -> SceneRenderItem:
        """Project one matching override into both item clip owners."""
        clip = self._clips.get((scene_id, item.descriptor.layer_id))
        if clip is None or (item.clip == clip and item.descriptor.clip == clip):
            return item
        return replace(
            item,
            descriptor=replace(item.descriptor, clip=clip),
            clip=clip,
        )
