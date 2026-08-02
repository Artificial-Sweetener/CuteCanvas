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

"""Selected scene-layer state independent of pixel-selection coverage."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from qpane.sdk.scene import LayerDescriptor, SceneDescriptor, SceneLayerHitTestResult


@dataclass(frozen=True, slots=True)
class SceneLayerSelection:
    """Identify one selected layer in one resolved scene."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID


class SceneLayerSelectionController:
    """Own an ordered scene-layer selection with one active member."""

    def __init__(
        self,
        changed: Callable[[tuple[SceneLayerSelection, ...]], None] | None = None,
    ) -> None:
        """Initialize without selected scene layers."""
        self._selections: tuple[SceneLayerSelection, ...] = ()
        self._changed = changed

    @property
    def current(self) -> SceneLayerSelection | None:
        """Return the active selection member, if any."""
        return self._selections[-1] if self._selections else None

    @property
    def selected(self) -> tuple[SceneLayerSelection, ...]:
        """Return selected identities with the active member last."""
        return self._selections

    def contains(self, scene_id: uuid.UUID, layer_id: uuid.UUID) -> bool:
        """Return whether an exact scene/layer identity is selected."""
        return SceneLayerSelection(scene_id, layer_id) in self._selections

    def select_hit(self, hit: SceneLayerHitTestResult) -> bool:
        """Select a selectable hit and report whether identity changed."""
        if not hit.selectable:
            return False
        return self.select(hit.scene_id, hit.layer_id)

    def select(self, scene_id: uuid.UUID, layer_id: uuid.UUID) -> bool:
        """Replace selection with one active scene/layer identity."""
        selection = SceneLayerSelection(scene_id=scene_id, layer_id=layer_id)
        if self._selections == (selection,):
            return False
        self._selections = (selection,)
        self._publish()
        return True

    def select_many(
        self,
        scene_id: uuid.UUID,
        layer_ids: tuple[uuid.UUID, ...],
        *,
        active_layer_id: uuid.UUID | None = None,
    ) -> bool:
        """Replace selection with unique same-scene identities."""
        unique_ids = tuple(dict.fromkeys(layer_ids))
        if active_layer_id is not None and active_layer_id not in unique_ids:
            raise ValueError("active_layer_id must be one of layer_ids")
        active_id = active_layer_id or (unique_ids[-1] if unique_ids else None)
        ordered_ids = tuple(
            layer_id for layer_id in unique_ids if layer_id != active_id
        ) + (() if active_id is None else (active_id,))
        selections = tuple(
            SceneLayerSelection(scene_id, layer_id) for layer_id in ordered_ids
        )
        if selections == self._selections:
            return False
        self._selections = selections
        self._publish()
        return True

    def add(self, scene_id: uuid.UUID, layer_id: uuid.UUID) -> bool:
        """Add one identity and make it active without collapsing selection."""
        selection = SceneLayerSelection(scene_id, layer_id)
        selections = tuple(
            candidate
            for candidate in self._selections
            if candidate.scene_id == scene_id and candidate != selection
        ) + (selection,)
        if selections == self._selections:
            return False
        self._selections = selections
        self._publish()
        return True

    def activate(self, scene_id: uuid.UUID, layer_id: uuid.UUID) -> bool:
        """Make one selected identity active without collapsing the set."""
        selection = SceneLayerSelection(scene_id, layer_id)
        if selection not in self._selections or self.current == selection:
            return False
        self._selections = tuple(
            candidate for candidate in self._selections if candidate != selection
        ) + (selection,)
        self._publish()
        return True

    def clear(self) -> bool:
        """Clear selection and report whether state changed."""
        if not self._selections:
            return False
        self._selections = ()
        self._publish()
        return True

    def resolve(self, scene: SceneDescriptor | None) -> LayerDescriptor | None:
        """Return the selected descriptor when it belongs to ``scene``."""
        selection = self.current
        if scene is None or selection is None or selection.scene_id != scene.scene_id:
            return None
        return next(
            (layer for layer in scene.layers if layer.layer_id == selection.layer_id),
            None,
        )

    def validate(self, scene: SceneDescriptor | None) -> bool:
        """Clear selection when its scene or layer is no longer resolved."""
        if not self._selections:
            return False
        if scene is None:
            return self.clear()
        layer_ids = {layer.layer_id for layer in scene.layers}
        selections = tuple(
            selection
            for selection in self._selections
            if selection.scene_id == scene.scene_id and selection.layer_id in layer_ids
        )
        if selections == self._selections:
            return False
        self._selections = selections
        self._publish()
        return True

    def _publish(self) -> None:
        """Notify the configured observer after identity changes."""
        if self._changed is not None:
            self._changed(self._selections)
