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
"""Publish provisional and durable shared-edge mapping sets."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from cutecanvas.scene.mapping_mutations import (
    LayerMappingMutationOwner,
    LayerMappingValue,
)
from cutecanvas.scene.mapping_preview import (
    LayerMappingPreview,
    SceneLayerMappingPreview,
)
from cutecanvas.scene.mutations import SceneMutationStatus
from qpane.sdk.scene import SceneDescriptor

from .shared_edge_history import SharedEdgeMappings


class SharedEdgeMappingPublication:
    """Own preview restoration and one atomic durable mapping commit."""

    def __init__(
        self,
        *,
        active_scene: Callable[[], SceneDescriptor | None],
        preview: SceneLayerMappingPreview,
        mutations: LayerMappingMutationOwner,
        preview_changed: Callable[[], None],
        committed: Callable[[], None],
    ) -> None:
        """Bind the authoritative preview, mutation, and publication owners."""
        self._active_scene = active_scene
        self._preview = preview
        self._mutations = mutations
        self._preview_changed = preview_changed
        self._committed = committed

    def restore(self, values: SharedEdgeMappings, is_base: bool) -> bool:
        """Restore one retained mapping set through the preview owner."""
        scene = self._active_scene()
        if scene is None:
            return False
        changed = (
            self._preview.clear()
            if is_base
            else self._preview.set_many(
                scene,
                tuple(
                    LayerMappingPreview(scene.scene_id, value.layer_id, value.mapping)
                    for value in values
                ),
            )
        )
        if changed:
            self._preview_changed()
        return changed

    def commit(self, scene_id: uuid.UUID, values: SharedEdgeMappings) -> bool:
        """Publish one exact coupled mapping set through durable history."""
        result = self._mutations.commit(scene_id, values)
        applied = result.status in {
            SceneMutationStatus.APPLIED,
            SceneMutationStatus.UNCHANGED,
        }
        if result.status is SceneMutationStatus.APPLIED:
            self._committed()
        return applied

    def settled_values(
        self,
        layer_ids: frozenset[uuid.UUID],
    ) -> SharedEdgeMappings | None:
        """Return the complete participant mapping set from current previews."""
        values = tuple(
            LayerMappingValue(preview.layer_id, preview.mapping)
            for preview in self._preview.previews
            if preview.layer_id in layer_ids
        )
        return (
            values
            if frozenset(value.layer_id for value in values) == layer_ids
            else None
        )

    def clear(self) -> bool:
        """Clear any retained preview and publish the presentation change."""
        changed = self._preview.clear()
        if changed:
            self._preview_changed()
        return changed


__all__ = ["SharedEdgeMappingPublication"]
