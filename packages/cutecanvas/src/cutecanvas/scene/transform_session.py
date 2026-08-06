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
"""Source-neutral affine transform sessions shared by editor tools."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from PySide6.QtCore import QPointF
from qpane.sdk.scene import (
    AffineTransformGeometry,
    LayerDescriptor,
    LayerTransform,
    SceneDescriptor,
    SceneLayerHitTestResult,
    TransformLocalBounds,
    TransformModifiers,
    TransformOperation,
    TransformOperationKind,
)

from .layer_geometry import LayerGeometryResolver
from .layer_selection import SceneLayerSelectionController
from .mutations import SceneMutationCoordinator, SceneMutationResult
from .transform_preview import SceneLayerTransformPreview


@dataclass(frozen=True, slots=True)
class LayerTransformBoxState:
    """Describe one selected layer's current transform-box geometry."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    bounds: TransformLocalBounds
    transform: LayerTransform
    unresolved: bool
    excluded_layer_ids: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class LayerTransformSession:
    """Retain one durable transform base across multiple pointer gestures."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    bounds: TransformLocalBounds
    initial_transform: LayerTransform


@dataclass(frozen=True, slots=True)
class LayerTransformGesture:
    """Capture one pointer operation within an unresolved transform session."""

    origin: QPointF
    operation: TransformOperation
    geometry: AffineTransformGeometry


class SceneLayerTransformController:
    """Own selected-layer affine preview, gesture, and durable resolution state."""

    def __init__(
        self,
        selection: SceneLayerSelectionController,
        preview: SceneLayerTransformPreview,
        mutations: SceneMutationCoordinator,
        geometry: LayerGeometryResolver,
    ) -> None:
        """Bind selection, transient presentation, and durable mutation owners."""
        self._selection = selection
        self._preview = preview
        self._mutations = mutations
        self._geometry = geometry
        self._session: LayerTransformSession | None = None
        self._gesture: LayerTransformGesture | None = None

    @property
    def active(self) -> bool:
        """Return whether an unresolved transform session exists."""
        return self._session is not None

    @property
    def gesture_active(self) -> bool:
        """Return whether a pointer gesture currently owns transform input."""
        return self._gesture is not None

    def box_state(self) -> LayerTransformBoxState | None:
        """Return detached geometry for the selected policy-enabled layer."""
        resolved = self._selected_layer()
        if resolved is None:
            return None
        _scene, layer = resolved
        bounds = self._bounds_for_layer(_scene, layer)
        if bounds is None or layer.transform is None:
            return None
        preview_transform = self._preview.transform_for(
            layer.scene_id,
            layer.layer_id,
        )
        transform = preview_transform or layer.transform
        return LayerTransformBoxState(
            layer.scene_id,
            layer.layer_id,
            bounds,
            transform,
            self._session is not None,
        )

    def begin_selected(
        self,
        operation: TransformOperation,
        scene_point: QPointF,
    ) -> bool:
        """Begin one affine gesture against the selected movable layer."""
        resolved = self._selected_layer()
        if resolved is None:
            return False
        scene, layer = resolved
        return self._begin_layer(scene, layer, operation, scene_point)

    def preview_selected_transform(self, transform: LayerTransform) -> bool:
        """Publish one cumulative selected-layer transform without a gesture."""
        resolved = self._selected_layer()
        if resolved is None:
            return False
        scene, layer = resolved
        if layer.transform is None:
            return False
        bounds = self._bounds_for_layer(scene, layer)
        if bounds is None:
            return False
        session = self._session
        if (
            session is None
            or session.scene_id != layer.scene_id
            or session.layer_id != layer.layer_id
        ):
            self.cancel()
            self._session = LayerTransformSession(
                layer.scene_id,
                layer.layer_id,
                bounds,
                layer.transform,
            )
        self._gesture = None
        return self._preview.set(layer.scene_id, layer.layer_id, transform)

    def begin_move(self, hit: SceneLayerHitTestResult, scene_point: QPointF) -> bool:
        """Select one hit layer and begin a translation gesture."""
        self._selection.select_hit(hit)
        resolved = self._mutations.find_layer(
            lambda layer: (
                layer.scene_id == hit.scene_id and layer.layer_id == hit.layer_id
            )
        )
        if resolved is None:
            return False
        scene, layer = resolved
        return self._begin_layer(
            scene,
            layer,
            TransformOperation(TransformOperationKind.MOVE),
            scene_point,
        )

    def update(
        self,
        scene_point: QPointF,
        modifiers: TransformModifiers | None = None,
    ) -> bool:
        """Publish an exact transient transform for the active pointer gesture."""
        session = self._session
        gesture = self._gesture
        if session is None or gesture is None:
            return False
        transform = gesture.geometry.transform_for_drag(
            gesture.operation,
            gesture.origin,
            scene_point,
            modifiers or TransformModifiers(),
        )
        return bool(
            transform is not None
            and self._preview.set(session.scene_id, session.layer_id, transform)
        )

    def end_gesture(
        self,
        scene_point: QPointF,
        modifiers: TransformModifiers | None = None,
    ) -> bool:
        """Finish pointer ownership while retaining unresolved preview geometry."""
        if self._gesture is None:
            return False
        changed = self.update(scene_point, modifiers)
        self._gesture = None
        return changed or self._session is not None

    def finish_move(self, scene_point: QPointF) -> SceneMutationResult | None:
        """Finish and immediately commit one Move-tool translation gesture."""
        if self._session is None:
            return None
        self.end_gesture(scene_point, TransformModifiers(proportional=False))
        return self.commit()

    def commit(self) -> SceneMutationResult | None:
        """Commit the cumulative unresolved transform as one history command."""
        session = self._session
        if session is None:
            return None
        preview_transform = self._preview.transform_for(
            session.scene_id,
            session.layer_id,
        )
        transform = preview_transform or session.initial_transform
        self._session = None
        self._gesture = None
        self._preview.clear()
        return self._mutations.set_transform(
            session.scene_id,
            session.layer_id,
            transform,
        )

    def cancel(self) -> bool:
        """Discard the complete unresolved transform and transient preview."""
        had_state = self._session is not None or self._gesture is not None
        self._session = None
        self._gesture = None
        return self._preview.clear() or had_state

    def suspend(self) -> bool:
        """Release pointer ownership without changing unresolved geometry."""
        had_gesture = self._gesture is not None
        self._gesture = None
        return had_gesture or self._session is not None

    def nudge_selected(
        self,
        delta_x: float,
        delta_y: float,
    ) -> SceneMutationResult | None:
        """Commit one keyboard translation for the selected movable layer."""
        resolved = self._selected_layer()
        if resolved is None:
            return None
        _scene, layer = resolved
        if layer.transform is None:
            return None
        return self._mutations.set_transform(
            layer.scene_id,
            layer.layer_id,
            layer.transform.translated(delta_x, delta_y),
        )

    def clear_selection(self) -> bool:
        """Clear persistent scene-layer selection."""
        return self._selection.clear()

    def synchronize_scene(self, scene: SceneDescriptor | None) -> bool:
        """Discard selection or transform state that no longer belongs to ``scene``."""
        changed = self._selection.validate(scene)
        session = self._session
        if session is None:
            return changed
        valid = bool(
            scene is not None
            and scene.scene_id == session.scene_id
            and any(layer.layer_id == session.layer_id for layer in scene.layers)
        )
        return changed if valid else self.cancel() or changed

    def _begin_layer(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        operation: TransformOperation,
        scene_point: QPointF,
    ) -> bool:
        """Begin a gesture while preserving any cumulative same-target preview."""
        if (
            not layer.interaction.selectable
            or not layer.interaction.movable
            or layer.transform is None
        ):
            return False
        bounds = self._bounds_for_layer(scene, layer)
        if bounds is None:
            return False
        preview_transform = self._preview.transform_for(
            layer.scene_id,
            layer.layer_id,
        )
        continuing = bool(
            self._session is not None
            and self._session.scene_id == layer.scene_id
            and self._session.layer_id == layer.layer_id
            and preview_transform is not None
        )
        if not continuing:
            self.cancel()
            self._session = LayerTransformSession(
                layer.scene_id,
                layer.layer_id,
                bounds,
                layer.transform,
            )
        base = (
            preview_transform
            if continuing and preview_transform is not None
            else layer.transform
        )
        self._gesture = LayerTransformGesture(
            QPointF(scene_point),
            operation,
            AffineTransformGeometry(bounds, base),
        )
        return True

    def _selected_layer(self) -> tuple[SceneDescriptor, LayerDescriptor] | None:
        """Resolve the selected movable layer through the scene coordinator."""
        selected = self._selection.current
        if selected is None:
            return None
        resolved = self._mutations.find_layer(
            lambda layer: (
                layer.scene_id == selected.scene_id
                and layer.layer_id == selected.layer_id
            )
        )
        if resolved is None:
            return None
        scene, layer = resolved
        if not layer.interaction.selectable or not layer.interaction.movable:
            return None
        return scene, layer

    def _bounds_for_layer(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
    ) -> TransformLocalBounds | None:
        """Prefer source-owned meaningful pixels over transparent storage edges."""
        bounds = self._geometry.resolved_local_bounds(layer)
        if bounds is None:
            return None
        return TransformLocalBounds(
            bounds.x(),
            bounds.y(),
            bounds.width(),
            bounds.height(),
        )
