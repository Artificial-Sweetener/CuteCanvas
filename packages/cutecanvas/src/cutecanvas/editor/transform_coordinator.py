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

import math
from collections.abc import Callable

from PySide6.QtCore import QPointF
from qpane.sdk.scene import (
    AffineTransformGeometry,
    LayerTransform,
    TransformHandle,
    TransformModifiers,
    TransformOperation,
)

from cutecanvas.snapping.transform import TransformSnapCoordinator
from cutecanvas.types import (
    EditorTransformCommand,
    EditorTransformSnapshot,
    EditorTransformTarget,
)

from ..scene.transform_session import LayerTransformBoxState
from .operation_contracts import (
    EditorOperation,
    EditorOperationResolution,
    EditorOperationTarget,
)
from .operation_resolution import EditorOperationResolver
from .pixel_movement import SelectedPixelMovementController
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
            self._snapping.begin(
                box,
                operation,
                scene_point,
                exclude_selection=target is EditorTransformTarget.SELECTION_CONTENT,
            )
            self._active_target = target
            self._gesture_active = True
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
        center = AffineTransformGeometry(state.bounds, state.transform).scene_center()
        delta = _command_transform(normalized, center)
        transform = state.transform.followed_by(delta)
        changed = (
            self._pixels.preview_scene_transform(transform)
            if target is EditorTransformTarget.SELECTION_CONTENT
            else self._layers.preview_scene_transform(transform)
        )
        if changed:
            self._active_target = target
            self._changed()
        return changed

    def commit(self) -> bool:
        """Commit the cumulative target preview as one chronological edit."""
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

    def cancel(self) -> bool:
        """Discard the cumulative target preview and restore source state."""
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

    def suspend(self) -> bool:
        """Release pointer ownership without resolving cumulative preview."""
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


def _command_transform(
    command: EditorTransformCommand,
    center: QPointF,
) -> LayerTransform:
    """Build one scene-space affine delta around a detached frame center."""
    if command is EditorTransformCommand.FLIP_HORIZONTAL:
        linear = (-1.0, 0.0, 0.0, 1.0)
    elif command is EditorTransformCommand.FLIP_VERTICAL:
        linear = (1.0, 0.0, 0.0, -1.0)
    else:
        angle = -90.0 if command is EditorTransformCommand.ROTATE_LEFT_90 else 90.0
        radians = math.radians(angle)
        cosine = round(math.cos(radians), 15)
        sine = round(math.sin(radians), 15)
        linear = (cosine, sine, -sine, cosine)
    m11, m12, m21, m22 = linear
    return LayerTransform(
        m11,
        m12,
        m21,
        m22,
        center.x() - (m11 * center.x() + m21 * center.y()),
        center.y() - (m12 * center.x() + m22 * center.y()),
    )


__all__ = ["EditorTransformCoordinator"]
