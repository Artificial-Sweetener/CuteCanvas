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
"""Public routing and policy for provisional editor-session history."""

from __future__ import annotations

from cutecanvas.edit_sessions import (
    EditSessionPolicy,
    EditSessionSnapshot,
    EditSessionUndoBoundary,
)
from cutecanvas.editor.session_coordination import EditSessionCoordinator


class EditSessionApiMixin:
    """Expose one active provisional session through the widget facade."""

    def editSessionCoordinator(self) -> EditSessionCoordinator:
        """Return the installed private session owner to editor collaborators."""
        interactions = self._scene_transform_interaction
        if interactions is None:
            raise AttributeError(
                "Edit session coordinator accessed before initialization"
            )
        return interactions.sessions

    def activeEditSession(self) -> EditSessionSnapshot | None:
        """Return detached state for the unresolved edit session, if any."""
        return self.editSessionCoordinator().snapshot

    def editSessionPolicy(self) -> EditSessionPolicy:
        """Return the current host-selected edit-session policy."""
        return self.editSessionCoordinator().policy

    def setEditSessionPolicy(self, policy: EditSessionPolicy) -> bool:
        """Set bounded-history and boundary behavior for future checkpoints."""
        return self.editSessionCoordinator().set_policy(policy)

    def editorUndoAvailable(self) -> bool:
        """Return whether unified editor Undo can act at its current boundary."""
        state = self.activeEditSession()
        if state is None:
            return self.sceneEditUndoAvailable()
        if state.gesture_active:
            return False
        return state.can_undo or (
            self.editSessionPolicy().undo_boundary
            is EditSessionUndoBoundary.CANCEL_SESSION
        )

    def editorRedoAvailable(self) -> bool:
        """Return whether unified editor Redo can act at its current boundary."""
        state = self.activeEditSession()
        return self.sceneEditRedoAvailable() if state is None else state.can_redo

    def undoEditorEdit(self) -> bool:
        """Undo within the active session before durable document history."""
        return self.editSessionCoordinator().undo(self.undoSceneEdit)

    def redoEditorEdit(self) -> bool:
        """Redo within the active session before durable document history."""
        return self.editSessionCoordinator().redo(self.redoSceneEdit)

    def applyActiveEditSession(self) -> bool:
        """Commit the active provisional result as one durable edit."""
        return self.editSessionCoordinator().apply()

    def cancelActiveEditSession(self) -> bool:
        """Restore the active session's immutable base and close it."""
        return self.editSessionCoordinator().cancel()


__all__ = ["EditSessionApiMixin"]
