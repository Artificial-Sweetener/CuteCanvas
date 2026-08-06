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
"""Host-facing affine transform session API."""

from __future__ import annotations

from cutecanvas.types import (
    EditorTransformCommand,
    EditorTransformSnapshot,
    EditorTransformTarget,
)


class TransformApiMixin:
    """Expose one target-neutral affine preview and resolution contract."""

    def editorTransformState(
        self,
        target: EditorTransformTarget,
    ) -> EditorTransformSnapshot:
        """Return detached affine availability and frame state for ``target``."""
        if not isinstance(target, EditorTransformTarget):
            raise TypeError("target must be EditorTransformTarget")
        return self.sceneLayerTransformInteraction().snapshot(target)

    def activateEditorTransform(self, target: EditorTransformTarget) -> bool:
        """Activate the transform tool against one explicit content authority."""
        if not isinstance(target, EditorTransformTarget):
            raise TypeError("target must be EditorTransformTarget")
        transform = self.sceneLayerTransformInteraction()
        if not transform.activate(target):
            return False
        return self.setControlMode(self.CONTROL_MODE_TRANSFORM)

    def applyEditorTransformCommand(self, command: EditorTransformCommand) -> bool:
        """Apply one cumulative frame-relative transform preview command."""
        if not isinstance(command, EditorTransformCommand):
            raise TypeError("command must be EditorTransformCommand")
        changed = self.sceneLayerTransformInteraction().apply_command(command)
        if changed:
            self.update()
        return changed

    def applyEditorTransform(self) -> bool:
        """Commit the complete unresolved affine preview as one edit."""
        return self.sceneLayerTransformInteraction().commit()

    def cancelEditorTransform(self) -> bool:
        """Discard the complete unresolved affine preview."""
        return self.sceneLayerTransformInteraction().cancel()


__all__ = ["TransformApiMixin"]
