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

"""Panel-coordinate adapter for generic scene-layer movement."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF

from .movement import SceneLayerMovementController
from .render_plan import SceneLayerHitTestResult


class SceneLayerMovementInteraction:
    """Adapt panel input to movement sessions and publish resulting changes."""

    def __init__(
        self,
        *,
        movement: SceneLayerMovementController,
        hit_test: Callable[[QPointF], SceneLayerHitTestResult | None],
        panel_to_scene: Callable[[QPointF], QPointF | None],
        publish_change: Callable[[], None],
        refresh_preview: Callable[[], None],
    ) -> None:
        """Capture coordinate, movement, and presentation collaborators."""
        self._movement = movement
        self._hit_test = hit_test
        self._panel_to_scene = panel_to_scene
        self._publish_change = publish_change
        self._refresh_preview = refresh_preview

    def begin(self, panel_point: QPointF) -> bool:
        """Begin movement for the top selectable covered scene layer."""
        hit = self._hit_test(panel_point)
        scene_point = self._panel_to_scene(panel_point)
        if hit is None or scene_point is None:
            self._movement.clear_selection()
            self._movement.cancel()
            return False
        return self._movement.begin(hit, scene_point)

    def update(self, panel_point: QPointF) -> bool:
        """Update transient placement from panel coordinates."""
        scene_point = self._panel_to_scene(panel_point)
        if scene_point is None or not self._movement.update(scene_point):
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

    def cancel(self) -> bool:
        """Discard transient movement without mutating the scene."""
        changed = self._movement.cancel()
        if changed:
            self._refresh_preview()
        return changed
