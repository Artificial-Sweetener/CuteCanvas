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
"""Host capability policy and operation-resolution facade."""

from __future__ import annotations

from cutecanvas.editor import EditorOperation
from cutecanvas.editor.interaction_policy import (
    CanvasInteractionMode,
    editor_policy_for_mode,
    mode_for_editor_policy,
)
from cutecanvas.types import (
    EditorIntent,
    EditorOperationState,
    EditorPolicy,
)
from PySide6.QtCore import QPoint, QPointF


class EditorPolicyApiMixin:
    """Expose host policy and read-only operation resolution."""

    def editorPolicy(self) -> EditorPolicy:
        """Return the immutable host capability policy."""
        return self._editor_policy.policy

    def setEditorPolicy(self, policy: EditorPolicy) -> bool:
        """Replace editor capabilities after cancelling provisional input."""
        if not isinstance(policy, EditorPolicy):
            raise TypeError("policy must be EditorPolicy")
        if policy == self._editor_policy.policy:
            return False
        self.interaction.cancel_active_editor_input()
        movement = self._editor_movement_interaction
        transform = self._scene_transform_interaction
        painting = self._painting
        if movement is not None:
            movement.cancel()
        if transform is not None:
            transform.cancel()
        if painting is not None:
            painting.cancel()
        changed = self._editor_policy.replace(policy)
        self.refreshCursor()
        self.update()
        return changed

    def interactionMode(self) -> CanvasInteractionMode:
        """Return the named profile matching the authoritative editor policy."""
        return mode_for_editor_policy(self.editorPolicy())

    def setInteractionMode(self, mode: CanvasInteractionMode) -> bool:
        """Apply one common host profile through the normal capability resolver."""
        return self.setEditorPolicy(editor_policy_for_mode(mode))

    def editorOperationState(
        self,
        intent: EditorIntent,
        panel_pos: QPoint | QPointF | None = None,
    ) -> EditorOperationState:
        """Resolve an editor intent without mutating document state."""
        if not isinstance(intent, EditorIntent):
            raise TypeError("intent must be EditorIntent")
        if panel_pos is not None and not isinstance(panel_pos, (QPoint, QPointF)):
            raise TypeError("panel_pos must be QPoint, QPointF, or None")
        operation = EditorOperation(intent.value)
        scene_point = (
            None
            if panel_pos is None
            else self.view().panel_to_scene_point(QPointF(panel_pos))
        )
        candidate_layer_id = None
        if operation is EditorOperation.MOVE and panel_pos is not None:
            interaction = self._scene_movement_interaction
            candidate = (
                None
                if interaction is None
                else interaction.candidate_at(QPointF(panel_pos))
            )
            candidate_layer_id = None if candidate is None else candidate.hit.layer_id
        resolution = self.editorOperationResolver().resolve(
            operation,
            scene_point=scene_point,
            candidate_layer_id=candidate_layer_id,
        )
        return EditorOperationState(
            intent=intent,
            allowed=resolution.allowed,
            denial=None if resolution.allowed else resolution.denial.value,
            alternatives=tuple(value.value for value in resolution.alternatives),
            scene_id=resolution.scene_id,
            layer_id=resolution.layer_id,
        )
