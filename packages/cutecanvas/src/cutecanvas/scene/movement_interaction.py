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

"""Panel-coordinate adapter for generic scene-layer movement."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPointF
from qpane.sdk.scene import SceneLayerHitTestResult

from .layer_move import SceneLayerMoveController
from .layer_selection import SceneLayerSelection, SceneLayerSelectionController
from .transform_session import LayerTransformBoxState


@dataclass(frozen=True, slots=True)
class LayerMoveCandidate:
    """Carry one hit-tested layer and its exact scene-space pointer point."""

    hit: SceneLayerHitTestResult
    scene_point: QPointF

    def __post_init__(self) -> None:
        """Detach mutable Qt geometry at the adapter boundary."""
        object.__setattr__(self, "scene_point", QPointF(self.scene_point))


class SceneLayerMovementInteraction:
    """Adapt panel input to movement sessions and publish resulting changes."""

    def __init__(
        self,
        *,
        movement: SceneLayerMoveController,
        selection: SceneLayerSelectionController,
        hit_test: Callable[[QPointF], SceneLayerHitTestResult | None],
        panel_to_scene: Callable[[QPointF], QPointF | None],
        publish_change: Callable[[], None],
        refresh_preview: Callable[[], None],
    ) -> None:
        """Capture coordinate, movement, and presentation collaborators."""
        self._movement = movement
        self._selection = selection
        self._hit_test = hit_test
        self._panel_to_scene = panel_to_scene
        self._publish_change = publish_change
        self._refresh_preview = refresh_preview
        self._hovered: SceneLayerSelection | None = None

    @property
    def hovered(self) -> SceneLayerSelection | None:
        """Return the move target currently under the pointer."""
        return self._hovered

    @property
    def selected(self) -> SceneLayerSelection | None:
        """Return the active member of the layer selection."""
        return self._selection.current

    def transform_box_state(self) -> LayerTransformBoxState | None:
        """Return current content-tight movement geometry for snapping."""
        return self._movement.box_state()

    def candidate_at(self, panel_point: QPointF) -> LayerMoveCandidate | None:
        """Hit-test one pointer without deciding editor operation policy."""
        hit = self._hit_test(panel_point)
        scene_point = self._panel_to_scene(panel_point)
        if hit is None or scene_point is None:
            return None
        return LayerMoveCandidate(hit, scene_point)

    def set_hover(self, candidate: LayerMoveCandidate | None) -> bool:
        """Publish the resolver-approved layer hover target."""
        hovered = None
        if candidate is not None:
            hovered = SceneLayerSelection(
                candidate.hit.scene_id,
                candidate.hit.layer_id,
            )
        if hovered == self._hovered:
            return False
        self._hovered = hovered
        self._refresh_preview()
        return True

    def clear_hover(self) -> bool:
        """Clear move-target feedback without changing layer selection."""
        if self._hovered is None:
            return False
        self._hovered = None
        self._refresh_preview()
        return True

    def begin(
        self,
        candidate: LayerMoveCandidate | None,
        scene_point: QPointF,
        *,
        auto_select: bool,
        extend_selection: bool,
    ) -> bool:
        """Resolve direct selection and begin movement for the selected set."""
        self.clear_hover()
        if auto_select:
            if candidate is None:
                return False
            hit = candidate.hit
            selected = self._selection
            if extend_selection:
                selected.add(hit.scene_id, hit.layer_id)
            elif not selected.contains(hit.scene_id, hit.layer_id):
                selected.select_hit(hit)
            else:
                selected.activate(hit.scene_id, hit.layer_id)
            scene_point = candidate.scene_point
        return self._movement.begin(scene_point)

    def update(self, panel_point: QPointF) -> bool:
        """Update transient placement from panel coordinates."""
        scene_point = self._panel_to_scene(panel_point)
        if scene_point is None or not self._movement.update(scene_point):
            return False
        self._refresh_preview()
        return True

    def update_scene(self, scene_point: QPointF) -> bool:
        """Update movement from an already normalized or snapped scene point."""
        if not self._movement.update(scene_point):
            return False
        self._refresh_preview()
        return True

    def finish(self, panel_point: QPointF) -> bool:
        """Commit the active movement and publish durable scene changes."""
        scene_point = self._panel_to_scene(panel_point)
        if scene_point is None:
            return self.cancel()
        result = self._movement.finish(scene_point)
        if result is not None and result.changed:
            self._publish_change()
            return True
        self._refresh_preview()
        return False

    def finish_scene(self, scene_point: QPointF) -> bool:
        """Commit movement from an already normalized or snapped scene point."""
        result = self._movement.finish(scene_point)
        if result is not None and result.changed:
            self._publish_change()
            return True
        self._refresh_preview()
        return False

    def cancel(self) -> bool:
        """Discard transient movement without mutating the scene."""
        changed = self._movement.cancel()
        if changed:
            self._refresh_preview()
        return changed

    def suspend(self) -> bool:
        """Preserve unresolved geometry while a temporary tool owns input."""
        return self._movement.suspend()

    def nudge(self, delta_x: int, delta_y: int) -> bool:
        """Commit one keyboard movement for selected movable layers."""
        result = self._movement.nudge(delta_x, delta_y)
        if result is None or not result.changed:
            return False
        self._publish_change()
        return True
