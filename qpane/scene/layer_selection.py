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

"""Selected scene-layer state independent of pixel-selection coverage."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from .model import SceneDescriptor
from .render_plan import SceneLayerHitTestResult


@dataclass(frozen=True, slots=True)
class SceneLayerSelection:
    """Identify one selected layer in one resolved scene."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID


class SceneLayerSelectionController:
    """Own persistent generic selection for direct layer interaction."""

    def __init__(
        self,
        changed: Callable[[SceneLayerSelection | None], None] | None = None,
    ) -> None:
        """Initialize without a selected scene layer."""
        self._selection: SceneLayerSelection | None = None
        self._changed = changed

    @property
    def current(self) -> SceneLayerSelection | None:
        """Return the current stable scene/layer selection."""
        return self._selection

    def select_hit(self, hit: SceneLayerHitTestResult) -> bool:
        """Select a selectable hit and report whether identity changed."""
        if not hit.selectable:
            return False
        return self.select(hit.scene_id, hit.layer_id)

    def select(self, scene_id: uuid.UUID, layer_id: uuid.UUID) -> bool:
        """Select one scene/layer identity and report whether it changed."""
        selection = SceneLayerSelection(scene_id=scene_id, layer_id=layer_id)
        if selection == self._selection:
            return False
        self._selection = selection
        self._publish()
        return True

    def clear(self) -> bool:
        """Clear selection and report whether state changed."""
        if self._selection is None:
            return False
        self._selection = None
        self._publish()
        return True

    def validate(self, scene: SceneDescriptor | None) -> bool:
        """Clear selection when its scene or layer is no longer resolved."""
        selection = self._selection
        if selection is None:
            return False
        if (
            scene is not None
            and scene.scene_id == selection.scene_id
            and any(layer.layer_id == selection.layer_id for layer in scene.layers)
        ):
            return False
        return self.clear()

    def _publish(self) -> None:
        """Notify the configured observer after identity changes."""
        if self._changed is not None:
            self._changed(self._selection)
