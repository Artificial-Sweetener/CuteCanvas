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
"""Panel-coordinate interaction for unresolved affine layer transforms."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPointF
from qpane.sdk.scene import (
    AffineTransformGeometry,
    TransformHandle,
    TransformModifiers,
    TransformOperation,
)

from ..scene.transform_session import (
    LayerTransformBoxState,
    SceneLayerTransformController,
)
from .operation_resolution import (
    EditorOperation,
    EditorOperationResolver,
    EditorOperationTarget,
)
from .pixel_movement import SelectedPixelMovementController


@dataclass(frozen=True, slots=True)
class TransformBoxPresentation:
    """Detached panel-space transform box consumed by tools and overlays."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    corners: tuple[QPointF, QPointF, QPointF, QPointF]
    handles: tuple[tuple[TransformHandle, QPointF], ...]
    center: QPointF
    unresolved: bool

    def __post_init__(self) -> None:
        """Detach mutable Qt points from interaction-owned geometry."""
        object.__setattr__(
            self, "corners", tuple(QPointF(point) for point in self.corners)
        )
        object.__setattr__(
            self,
            "handles",
            tuple((handle, QPointF(point)) for handle, point in self.handles),
        )
        object.__setattr__(self, "center", QPointF(self.center))


class SceneLayerTransformInteraction:
    """Adapt panel input and publication around one affine session owner."""

    def __init__(
        self,
        *,
        transforms: SceneLayerTransformController,
        panel_to_scene: Callable[[QPointF], QPointF | None],
        scene_to_panel: Callable[[QPointF], QPointF | None],
        publish_change: Callable[[], None],
        refresh_preview: Callable[[], None],
    ) -> None:
        """Bind coordinate conversion and facade publication callbacks."""
        self._transforms = transforms
        self._panel_to_scene = panel_to_scene
        self._scene_to_panel = scene_to_panel
        self._publish_change = publish_change
        self._refresh_preview = refresh_preview

    def presentation(self) -> TransformBoxPresentation | None:
        """Return current selected-layer transform geometry in panel coordinates."""
        state = self._transforms.box_state()
        return _project_presentation(state, self._scene_to_panel)

    def box_state(self) -> LayerTransformBoxState | None:
        """Return source-neutral selected-layer box state."""
        return self._transforms.box_state()

    def project_presentation(
        self,
        state: LayerTransformBoxState | None,
    ) -> TransformBoxPresentation | None:
        """Project detached affine box state into panel coordinates."""
        return _project_presentation(state, self._scene_to_panel)

    def panel_to_scene(self, panel_point: QPointF) -> QPointF | None:
        """Map one panel point into scene coordinates."""
        return self._panel_to_scene(panel_point)

    def begin_scene(self, operation: TransformOperation, scene_point: QPointF) -> bool:
        """Begin one layer operation from a resolved scene point."""
        return self._transforms.begin_selected(operation, scene_point)

    def update_scene(
        self,
        scene_point: QPointF,
        modifiers: TransformModifiers,
    ) -> bool:
        """Update layer geometry from a resolved scene point."""
        if not self._transforms.update(scene_point, modifiers):
            return False
        self._refresh_preview()
        return True

    def end_scene(
        self,
        scene_point: QPointF,
        modifiers: TransformModifiers,
    ) -> bool:
        """End layer pointer ownership from a resolved scene point."""
        changed = self._transforms.end_gesture(scene_point, modifiers)
        if changed:
            self._refresh_preview()
        return changed

    def commit(self) -> bool:
        """Commit the cumulative affine session as one chronological edit."""
        result = self._transforms.commit()
        if result is not None and result.changed:
            self._publish_change()
            return True
        self._refresh_preview()
        return result is not None

    def cancel(self) -> bool:
        """Cancel the complete unresolved affine session."""
        changed = self._transforms.cancel()
        if changed:
            self._refresh_preview()
        return changed

    def suspend(self) -> bool:
        """Release a gesture without changing unresolved preview geometry."""
        return self._transforms.suspend()


class EditorTransformInteraction:
    """Give selected pixels priority over whole-layer affine transforms."""

    def __init__(
        self,
        *,
        pixels: SelectedPixelMovementController,
        layers: SceneLayerTransformInteraction,
        operations: EditorOperationResolver,
    ) -> None:
        """Bind the two authoritative transform targets without duplicating state."""
        self._pixels = pixels
        self._layers = layers
        self._operations = operations
        self._active: str | None = None

    def presentation(self) -> TransformBoxPresentation | None:
        """Return selected-pixel geometry first, or selected-layer geometry."""
        resolution = self._operations.resolve(EditorOperation.TRANSFORM)
        if not resolution.allowed:
            return None
        if resolution.target in {
            EditorOperationTarget.FLOATING_PIXELS,
            EditorOperationTarget.SELECTED_PIXELS,
        }:
            return self._layers.project_presentation(self._pixels.transform_box_state())
        return self._layers.presentation()

    def begin(self, operation: TransformOperation, panel_point: QPointF) -> bool:
        """Begin the selection-priority affine branch."""
        scene_point = self._layers.panel_to_scene(panel_point)
        if scene_point is None:
            return False
        resolution = self._operations.resolve(
            EditorOperation.TRANSFORM,
            scene_point=scene_point,
        )
        if not resolution.allowed:
            return False
        if resolution.target in {
            EditorOperationTarget.FLOATING_PIXELS,
            EditorOperationTarget.SELECTED_PIXELS,
        }:
            if not self._pixels.begin_transform(operation, scene_point):
                return False
            self._active = "pixels"
            return True
        if (
            resolution.target is not EditorOperationTarget.LAYER
            or not self._layers.begin_scene(operation, scene_point)
        ):
            return False
        self._active = "layer"
        return True

    def update(self, panel_point: QPointF, modifiers: TransformModifiers) -> bool:
        """Update the affine branch that owns pointer input."""
        scene_point = self._layers.panel_to_scene(panel_point)
        if scene_point is None:
            return False
        if self._active == "pixels":
            return self._pixels.update_transform(scene_point, modifiers)
        if self._active == "layer":
            return self._layers.update_scene(scene_point, modifiers)
        return False

    def end_gesture(
        self,
        panel_point: QPointF,
        modifiers: TransformModifiers,
    ) -> bool:
        """Release pointer ownership without resolving cumulative geometry."""
        scene_point = self._layers.panel_to_scene(panel_point)
        if scene_point is None:
            return self.suspend()
        if self._active == "pixels":
            return self._pixels.finish_transform(scene_point, modifiers)
        if self._active == "layer":
            return self._layers.end_scene(scene_point, modifiers)
        return False

    def commit(self) -> bool:
        """Commit the unresolved target through its authoritative owner."""
        active = self._active
        self._active = None
        if active == "pixels" or self._pixels.transforming:
            return self._pixels.commit_transform()
        return self._layers.commit()

    def cancel(self) -> bool:
        """Cancel the unresolved target through its authoritative owner."""
        active = self._active
        self._active = None
        if active == "pixels" or self._pixels.transforming:
            return self._pixels.cancel()
        return self._layers.cancel()

    def suspend(self) -> bool:
        """Release pointer ownership while preserving unresolved geometry."""
        if self._active == "pixels":
            return self._pixels.suspend_transform()
        if self._active == "layer":
            return self._layers.suspend()
        return False


def _project_presentation(
    state: LayerTransformBoxState | None,
    scene_to_panel: Callable[[QPointF], QPointF | None],
) -> TransformBoxPresentation | None:
    """Project one detached affine box through a panel coordinate adapter."""
    if state is None:
        return None
    geometry = AffineTransformGeometry(state.bounds, state.transform)
    handles = tuple(
        (handle, scene_to_panel(geometry.scene_point(handle)))
        for handle in TransformHandle
    )
    center = scene_to_panel(geometry.scene_center())
    if center is None or any(point is None for _handle, point in handles):
        return None
    handle_points = tuple(
        (handle, point) for handle, point in handles if point is not None
    )
    by_handle = dict(handle_points)
    return TransformBoxPresentation(
        state.scene_id,
        state.layer_id,
        (
            by_handle[TransformHandle.TOP_LEFT],
            by_handle[TransformHandle.TOP_RIGHT],
            by_handle[TransformHandle.BOTTOM_RIGHT],
            by_handle[TransformHandle.BOTTOM_LEFT],
        ),
        handle_points,
        center,
        state.unresolved,
    )
