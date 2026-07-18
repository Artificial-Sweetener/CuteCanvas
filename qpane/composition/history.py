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

"""Composition-scoped history for durable scene-layer placement changes."""

from __future__ import annotations

import uuid

from ..scene.model import LayerPlacementChange


class LayerPlacementHistory:
    """Own undo and redo stacks for composition-layer placement commands."""

    def __init__(self, *, limit: int = 100) -> None:
        """Initialize empty scene-scoped history with a bounded command count."""
        if limit <= 0:
            raise ValueError("placement history limit must be positive")
        self._limit = limit
        self._undo_by_scene: dict[uuid.UUID, list[LayerPlacementChange]] = {}
        self._redo_by_scene: dict[uuid.UUID, list[LayerPlacementChange]] = {}

    def record(self, command: LayerPlacementChange) -> bool:
        """Record a changed placement and clear that scene's redo branch."""
        if command.before == command.after:
            return False
        undo = self._undo_by_scene.setdefault(command.scene_id, [])
        undo.append(command)
        del undo[: max(0, len(undo) - self._limit)]
        self._redo_by_scene.pop(command.scene_id, None)
        return True

    def undo_candidate(self, scene_id: uuid.UUID) -> LayerPlacementChange | None:
        """Return the next command to undo without advancing history."""
        commands = self._undo_by_scene.get(scene_id)
        return commands[-1] if commands else None

    def redo_candidate(self, scene_id: uuid.UUID) -> LayerPlacementChange | None:
        """Return the next command to redo without advancing history."""
        commands = self._redo_by_scene.get(scene_id)
        return commands[-1] if commands else None

    def commit_undo(self, command: LayerPlacementChange) -> bool:
        """Advance one successfully applied command from undo to redo."""
        undo = self._undo_by_scene.get(command.scene_id)
        if not undo or undo[-1] != command:
            return False
        undo.pop()
        self._redo_by_scene.setdefault(command.scene_id, []).append(command)
        return True

    def commit_redo(self, command: LayerPlacementChange) -> bool:
        """Advance one successfully applied command from redo to undo."""
        redo = self._redo_by_scene.get(command.scene_id)
        if not redo or redo[-1] != command:
            return False
        redo.pop()
        self._undo_by_scene.setdefault(command.scene_id, []).append(command)
        return True

    def clear_scene(self, scene_id: uuid.UUID) -> None:
        """Discard placement history owned by one removed or replaced scene."""
        self._undo_by_scene.pop(scene_id, None)
        self._redo_by_scene.pop(scene_id, None)

    def clear(self) -> None:
        """Discard all placement history."""
        self._undo_by_scene.clear()
        self._redo_by_scene.clear()
