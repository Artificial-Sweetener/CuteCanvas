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

"""Generic scene-layer movement sessions and durable placement commits."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from PySide6.QtCore import QPointF

from .model import LayerPlacement, SceneDescriptor
from .mutations import SceneMutationCoordinator, SceneMutationResult
from .placement_preview import SceneLayerPlacementPreview
from .render_plan import SceneLayerHitTestResult
from .selection import SceneLayerSelectionController


@dataclass(frozen=True, slots=True)
class LayerMoveSession:
    """Capture immutable placement and pointer state for one layer drag."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    origin: QPointF
    initial_placement: LayerPlacement


class SceneLayerMovementController:
    """Own selection, preview, and commit coordination for layer movement."""

    def __init__(
        self,
        selection: SceneLayerSelectionController,
        preview: SceneLayerPlacementPreview,
        mutations: SceneMutationCoordinator,
    ) -> None:
        """Capture the authoritative collaborators for movement state."""
        self._selection = selection
        self._preview = preview
        self._mutations = mutations
        self._session: LayerMoveSession | None = None

    @property
    def active(self) -> bool:
        """Return whether a movable layer currently owns the drag sequence."""
        return self._session is not None

    def begin(self, hit: SceneLayerHitTestResult, scene_point: QPointF) -> bool:
        """Select ``hit`` and begin movement when its policy permits it."""
        self.cancel()
        self._selection.select_hit(hit)
        resolved = self._mutations.find_layer(
            lambda layer: (
                layer.scene_id == hit.scene_id and layer.layer_id == hit.layer_id
            )
        )
        if resolved is None:
            return False
        _scene, layer = resolved
        if not layer.interaction.selectable or not layer.interaction.movable:
            return False
        self._session = LayerMoveSession(
            scene_id=layer.scene_id,
            layer_id=layer.layer_id,
            origin=QPointF(scene_point),
            initial_placement=layer.placement,
        )
        return True

    def update(self, scene_point: QPointF) -> bool:
        """Update transient placement from the active pointer delta."""
        session = self._session
        if session is None:
            return False
        delta = scene_point - session.origin
        initial = session.initial_placement
        return self._preview.set(
            session.scene_id,
            session.layer_id,
            LayerPlacement(
                x=initial.x + delta.x(),
                y=initial.y + delta.y(),
                width=initial.width,
                height=initial.height,
            ),
        )

    def finish(self, scene_point: QPointF) -> SceneMutationResult | None:
        """Commit the final absolute placement and clear transient state."""
        session = self._session
        if session is None:
            return None
        self.update(scene_point)
        preview = self._preview.current
        placement = session.initial_placement if preview is None else preview.placement
        self._session = None
        self._preview.clear()
        return self._mutations.set_placement(
            session.scene_id,
            session.layer_id,
            placement,
        )

    def cancel(self) -> bool:
        """Discard the active movement session and transient placement."""
        had_session = self._session is not None
        self._session = None
        return self._preview.clear() or had_session

    def clear_selection(self) -> bool:
        """Clear persistent scene-layer selection."""
        return self._selection.clear()

    def synchronize_scene(self, scene: SceneDescriptor | None) -> bool:
        """Discard selection or movement that no longer belongs to ``scene``."""
        changed = self._selection.validate(scene)
        session = self._session
        if session is None:
            return changed
        session_valid = (
            scene is not None
            and scene.scene_id == session.scene_id
            and any(layer.layer_id == session.layer_id for layer in scene.layers)
        )
        if session_valid:
            return changed
        return self.cancel() or changed
