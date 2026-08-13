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
"""Coordinate one affine lifecycle across selection and layer targets."""

from __future__ import annotations

from collections.abc import Callable

from cutecanvas.snapping.transform import TransformSnapCoordinator
from cutecanvas.types import (
    EditorTransformCommand,
    EditorTransformSnapshot,
    EditorTransformTarget,
)
from PySide6.QtCore import QPointF
from qpane.sdk.scene import (
    AffineTransformGeometry,
    LayerMapping,
    TransformHandle,
    TransformModifiers,
    TransformOperation,
)

from ..scene.transform_session import LayerTransformBoxState
from .operation_contracts import (
    EditorOperation,
    EditorOperationResolution,
    EditorOperationTarget,
)
from .operation_resolution import EditorOperationResolver
from .pixel_movement import SelectedPixelMovementController
from .session_coordination import EditSessionCoordinator
from .transform_commands import command_label, command_transform, operation_label
from .transform_history import TransformProvisionalSession
from .transform_interaction import (
    SceneLayerTransformInteraction,
    TransformBoxPresentation,
)


class EditorTransformCoordinator:
    """Own target choice, cumulative preview, and resolution for affine edits."""

    def __init__(
        self,
        *,
        pixels: SelectedPixelMovementController,
        layers: SceneLayerTransformInteraction,
        operations: EditorOperationResolver,
        snapping: TransformSnapCoordinator,
        sessions: EditSessionCoordinator,
        changed: Callable[[], None],
    ) -> None:
        """Bind focused target adapters to one target-neutral lifecycle."""
        self._pixels = pixels
        self._layers = layers
        self._operations = operations
        self._snapping = snapping
        self._changed = changed
        self._requested_target: EditorTransformTarget | None = None
        self._active_target: EditorTransformTarget | None = None
        self._gesture_active = False
        self._gesture_label = "Transform"
        self._provisional = TransformProvisionalSession(
            sessions=sessions,
            restore=self._restore_checkpoint,
            apply_transform=self._commit_current,
            cancel_transform=self._cancel_current,
            suspend_transform=self._suspend_current,
        )

    @property
    def target(self) -> EditorTransformTarget | None:
        """Return the explicit or currently resolved target identity."""
        return self._active_target or self._requested_target or self._auto_target()

    def activate(self, target: EditorTransformTarget | None = None) -> bool:
        """Choose the target used by subsequent gestures and commands."""
        normalized = None if target is None else EditorTransformTarget(target)
        resolution = self._resolve(normalized)
        if not resolution.allowed:
            return False
        if self._active_target is not None and self._active_target != normalized:
            self.cancel()
        self._requested_target = normalized
        self._changed()
        return True

    def snapshot(
        self,
        target: EditorTransformTarget | None = None,
    ) -> EditorTransformSnapshot:
        """Return detached scene-space state for one explicit affine target."""
        normalized = self.target if target is None else EditorTransformTarget(target)
        if normalized is None:
            normalized = EditorTransformTarget.SELECTION_CONTENT
        resolution = self._resolve(normalized)
        state = self._box_state(normalized) if resolution.allowed else None
        if state is None:
            return EditorTransformSnapshot(
                normalized,
                False,
                resolution.denial.value,
                resolution.scene_id,
                resolution.layer_id,
            )
        geometry = AffineTransformGeometry(state.bounds, state.transform)
        return EditorTransformSnapshot(
            normalized,
            True,
            None,
            state.scene_id,
            state.layer_id,
            (
                geometry.scene_point(TransformHandle.TOP_LEFT),
                geometry.scene_point(TransformHandle.TOP_RIGHT),
                geometry.scene_point(TransformHandle.BOTTOM_RIGHT),
                geometry.scene_point(TransformHandle.BOTTOM_LEFT),
            ),
            geometry.scene_center(),
            state.unresolved,
            self._gesture_active and normalized is self._active_target,
        )

    def presentation(self) -> TransformBoxPresentation | None:
        """Project current target geometry into panel coordinates."""
        target = self.target
        return (
            None
            if target is None
            else self._layers.project_presentation(self._box_state(target))
        )

    def begin(self, operation: TransformOperation, panel_point: QPointF) -> bool:
        """Begin one gesture through the selected target adapter."""
        scene_point = self._layers.panel_to_scene(panel_point)
        target = self.target
        if scene_point is None or target is None or not self._resolve(target).allowed:
            return False
        box = self._box_state(target)
        started = (
            self._pixels.begin_transform(operation, scene_point)
            if target is EditorTransformTarget.SELECTION_CONTENT
            else self._layers.begin_scene(operation, scene_point)
        )
        if started:
            self._active_target = target
            if box is None or not self._provisional.begin(box.transform):
                self._cancel_target(target)
                self._active_target = None
                return False
            self._snapping.begin(
                box,
                operation,
                scene_point,
                exclude_selection=target is EditorTransformTarget.SELECTION_CONTENT,
            )
            self._gesture_label = operation_label(operation)
            self._gesture_active = True
            self._provisional.begin_gesture()
            self._changed()
        return started

    def update(self, panel_point: QPointF, modifiers: TransformModifiers) -> bool:
        """Update the adapter that owns the active pointer gesture."""
        scene_point = self._layers.panel_to_scene(panel_point)
        if scene_point is None:
            return False
        scene_point = self._snapping.resolve(scene_point, modifiers)
        if self._active_target is EditorTransformTarget.SELECTION_CONTENT:
            changed = self._pixels.update_transform(scene_point, modifiers)
        elif self._active_target is EditorTransformTarget.LAYER_CONTENT:
            changed = self._layers.update_scene(scene_point, modifiers)
        else:
            return False
        if changed:
            self._changed()
        return changed

    def end_gesture(
        self,
        panel_point: QPointF,
        modifiers: TransformModifiers,
    ) -> bool:
        """Release pointer ownership while preserving cumulative preview."""
        scene_point = self._layers.panel_to_scene(panel_point)
        if scene_point is None:
            return self.suspend()
        scene_point = self._snapping.resolve(scene_point, modifiers)
        if self._active_target is EditorTransformTarget.SELECTION_CONTENT:
            changed = self._pixels.finish_transform(scene_point, modifiers)
        elif self._active_target is EditorTransformTarget.LAYER_CONTENT:
            changed = self._layers.end_scene(scene_point, modifiers)
        else:
            return False
        self._snapping.clear()
        self._gesture_active = False
        self._settle_current(self._gesture_label)
        self._changed()
        return changed

    def apply_command(self, command: EditorTransformCommand) -> bool:
        """Apply one frame-relative command to the original session preview."""
        self._snapping.clear()
        normalized = EditorTransformCommand(command)
        target = self.target
        state = None if target is None else self._box_state(target)
        if target is None or state is None:
            return False
        self._active_target = target
        if not self._provisional.begin(state.transform):
            self._active_target = None
            return False
        center = AffineTransformGeometry(state.bounds, state.transform).scene_center()
        delta = command_transform(normalized, center)
        transform = state.transform.followed_by(delta)
        changed = (
            self._pixels.preview_scene_transform(transform)
            if target is EditorTransformTarget.SELECTION_CONTENT
            else self._layers.preview_scene_transform(transform)
        )
        if changed:
            self._settle_current(command_label(normalized))
            self._changed()
        return changed

    def commit(self) -> bool:
        """Commit the cumulative target preview as one chronological edit."""
        return self._provisional.apply() if self._provisional.active else False

    def cancel(self) -> bool:
        """Discard the cumulative target preview and restore source state."""
        return self._provisional.cancel() if self._provisional.active else False

    def suspend(self) -> bool:
        """Release pointer ownership without resolving cumulative preview."""
        return self._provisional.suspend() if self._provisional.active else False

    def _commit_current(self) -> bool:
        """Commit the active target after provisional history resolves."""
        self._snapping.clear()
        target = self._active_target or self.target
        had_context = target is not None
        gesture_active = self._gesture_active
        changed = (
            self._pixels.commit_transform()
            if target is EditorTransformTarget.SELECTION_CONTENT
            else (
                self._layers.commit()
                if target is EditorTransformTarget.LAYER_CONTENT
                else False
            )
        )
        self._active_target = None
        self._gesture_active = False
        if changed or gesture_active:
            self._changed()
        return changed or had_context

    def _cancel_current(self) -> bool:
        """Cancel the active target after provisional history resolves."""
        self._snapping.clear()
        target = self._active_target or self.target
        had_context = target is not None
        changed = (
            self._pixels.cancel()
            if target is EditorTransformTarget.SELECTION_CONTENT
            else (
                self._layers.cancel()
                if target is EditorTransformTarget.LAYER_CONTENT
                else False
            )
        )
        gesture_active = self._gesture_active
        self._active_target = None
        self._gesture_active = False
        if changed or gesture_active:
            self._changed()
        return changed or had_context

    def _suspend_current(self) -> bool:
        """Suspend active target input while retaining provisional history."""
        self._snapping.clear()
        gesture_active = self._gesture_active
        self._gesture_active = False
        if self._active_target is EditorTransformTarget.SELECTION_CONTENT:
            changed = self._pixels.suspend_transform()
        elif self._active_target is EditorTransformTarget.LAYER_CONTENT:
            changed = self._layers.suspend()
        else:
            changed = False
        if gesture_active:
            self._changed()
        return changed or gesture_active

    def _settle_current(self, label: str) -> bool:
        """Retain one settled affine mapping and publish new history state."""
        target = self._active_target
        state = None if target is None else self._box_state(target)
        return state is not None and self._provisional.settle(state.transform, label)

    def _restore_checkpoint(self, transform: LayerMapping) -> bool:
        """Publish one retained mapping through the active target adapter."""
        target = self._active_target
        if target is None:
            return False
        changed = (
            self._pixels.preview_scene_transform(transform)
            if target is EditorTransformTarget.SELECTION_CONTENT
            else self._layers.preview_scene_transform(transform)
        )
        self._changed()
        return changed

    def _cancel_target(self, target: EditorTransformTarget) -> bool:
        """Cancel one target adapter without resolving coordinator state."""
        return (
            self._pixels.cancel()
            if target is EditorTransformTarget.SELECTION_CONTENT
            else self._layers.cancel()
        )

    def _resolve(
        self,
        target: EditorTransformTarget | None,
    ) -> EditorOperationResolution:
        """Resolve a public target through the authoritative operation policy."""
        if target is None:
            return self._operations.resolve(EditorOperation.TRANSFORM)
        operation_target = (
            EditorOperationTarget.SELECTED_PIXELS
            if target is EditorTransformTarget.SELECTION_CONTENT
            else EditorOperationTarget.LAYER
        )
        return self._operations.resolve_transform_target(operation_target)

    def _auto_target(self) -> EditorTransformTarget | None:
        """Map the normal selection-priority resolution to a public target."""
        resolution = self._resolve(None)
        if not resolution.allowed:
            return None
        if resolution.target in {
            EditorOperationTarget.FLOATING_PIXELS,
            EditorOperationTarget.SELECTED_PIXELS,
        }:
            return EditorTransformTarget.SELECTION_CONTENT
        if resolution.target is EditorOperationTarget.LAYER:
            return EditorTransformTarget.LAYER_CONTENT
        return None

    def _box_state(
        self,
        target: EditorTransformTarget,
    ) -> LayerTransformBoxState | None:
        """Return source-neutral affine geometry from one focused adapter."""
        return (
            self._pixels.transform_box_state()
            if target is EditorTransformTarget.SELECTION_CONTENT
            else self._layers.box_state()
        )


__all__ = ["EditorTransformCoordinator"]
