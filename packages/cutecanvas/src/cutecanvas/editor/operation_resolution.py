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
"""Authoritative capability, policy, and state resolution for editor intents."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from PySide6.QtCore import QPointF

from cutecanvas.coverage.containment import coverage_contains
from qpane.sdk.scene import LayerDescriptor, SceneDescriptor

from ..painting.targets import (
    PaintTargetContext,
    PaintTargetIdentity,
)
from ..scene.layer_geometry import LayerGeometryResolver
from ..scene.layer_selection import SceneLayerSelectionController
from ..scene.mutations import SceneMutationCoordinator
from ..scene.pixel_owners import LayerPixelOwnerRegistry
from ..selection import PixelSelectionService
from ..types import EditorCapability, PaintTargetKind
from .operation_contracts import (
    EditorOperation,
    EditorOperationAlternative,
    EditorOperationDenial,
    EditorOperationResolution,
    EditorOperationTarget,
)
from .pixel_move_target import (
    SelectedPixelMoveTarget,
    SelectedPixelMoveTargetResolver,
)
from .source_operations import EditorSourceOperationRegistry


class EditorOperationResolver:
    """Resolve editor intents through authoritative source owners and host policy."""

    def __init__(
        self,
        *,
        active_scene: Callable[[], SceneDescriptor | None],
        scene_mutations: SceneMutationCoordinator,
        layer_selection: SceneLayerSelectionController,
        pixel_selection: PixelSelectionService,
        selected_pixels: SelectedPixelMoveTargetResolver,
        floating_pixels_active: Callable[[], bool],
        floating_pixels_can_begin: Callable[[QPointF], bool],
        active_paint_target: Callable[[], PaintTargetIdentity | None],
        default_paint_target_available: Callable[[], bool],
        paint_target_supported: Callable[[PaintTargetContext], bool],
        pixel_owners: LayerPixelOwnerRegistry,
        layer_geometry: LayerGeometryResolver,
        source_operations: EditorSourceOperationRegistry,
        capability_allowed: Callable[[EditorCapability], bool],
    ) -> None:
        """Bind state owners without taking ownership of document or pixel state."""
        self._active_scene = active_scene
        self._scene_mutations = scene_mutations
        self._layer_selection = layer_selection
        self._pixel_selection = pixel_selection
        self._selected_pixels = selected_pixels
        self._floating_pixels_active = floating_pixels_active
        self._floating_pixels_can_begin = floating_pixels_can_begin
        self._active_paint_target = active_paint_target
        self._default_paint_target_available = default_paint_target_available
        self._paint_target_supported = paint_target_supported
        self._pixel_owners = pixel_owners
        self._layer_geometry = layer_geometry
        self._source_operations = source_operations
        self._capability_allowed = capability_allowed

    def resolve(
        self,
        operation: EditorOperation,
        *,
        scene_point: QPointF | None = None,
        candidate_layer_id: uuid.UUID | None = None,
    ) -> EditorOperationResolution:
        """Resolve one operation against the exact current editor state."""
        operation = EditorOperation(operation)
        scene = self._active_scene()
        if scene is None:
            return self._denied(operation, EditorOperationDenial.NO_ACTIVE_SCENE)
        if operation is EditorOperation.SELECT_PIXELS:
            return (
                self._allowed(
                    operation,
                    EditorOperationTarget.PIXEL_SELECTION,
                    scene.scene_id,
                    None,
                )
                if self._capability_allowed(EditorCapability.SELECT_PIXELS)
                else self._denied(
                    operation,
                    EditorOperationDenial.HOST_POLICY_DENIED,
                    scene_id=scene.scene_id,
                )
            )
        if operation in {EditorOperation.MOVE, EditorOperation.TRANSFORM}:
            return self._resolve_geometry(
                operation,
                scene,
                scene_point,
                candidate_layer_id,
                target_preference=None,
            )
        if operation is EditorOperation.PAINT:
            return self._resolve_paint(scene)
        layer = self._selected_layer(scene)
        if layer is None:
            return self._denied(
                operation,
                EditorOperationDenial.NO_SELECTED_LAYER,
                scene_id=scene.scene_id,
            )
        return self._resolve_delete(scene, layer)

    def resolve_transform_target(
        self,
        target: EditorOperationTarget,
    ) -> EditorOperationResolution:
        """Resolve one explicit affine target without changing editor state."""
        if target not in {
            EditorOperationTarget.SELECTED_PIXELS,
            EditorOperationTarget.LAYER,
        }:
            raise ValueError("transform target must be selected pixels or layer")
        scene = self._active_scene()
        if scene is None:
            return self._denied(
                EditorOperation.TRANSFORM,
                EditorOperationDenial.NO_ACTIVE_SCENE,
            )
        return self._resolve_geometry(
            EditorOperation.TRANSFORM,
            scene,
            None,
            None,
            target_preference=target,
        )

    def _resolve_geometry(
        self,
        operation: EditorOperation,
        scene: SceneDescriptor,
        scene_point: QPointF | None,
        candidate_layer_id: uuid.UUID | None,
        *,
        target_preference: EditorOperationTarget | None,
    ) -> EditorOperationResolution:
        """Apply floating, selected-pixel, then whole-layer precedence."""
        selected = self._layer_selection.current
        if target_preference is EditorOperationTarget.LAYER:
            if self._floating_pixels_active():
                return self._denied(
                    operation,
                    EditorOperationDenial.FLOATING_PIXELS_ACTIVE,
                    scene_id=scene.scene_id,
                    layer_id=None if selected is None else selected.layer_id,
                )
            return self._resolve_layer_geometry(
                operation,
                scene,
                candidate_layer_id,
            )
        if self._floating_pixels_active():
            if (
                operation is EditorOperation.MOVE
                and scene_point is not None
                and not self._floating_pixels_can_begin(scene_point)
            ):
                return self._denied(
                    operation,
                    EditorOperationDenial.POINTER_OUTSIDE_SELECTION,
                    scene_id=scene.scene_id,
                    layer_id=None if selected is None else selected.layer_id,
                )
            return self._geometry_allowed(
                operation,
                EditorOperationTarget.FLOATING_PIXELS,
                scene.scene_id,
                None if selected is None else selected.layer_id,
            )
        selected_pixels = self._selected_pixels.resolve_selected()
        if selected_pixels is not None:
            if (
                operation is EditorOperation.MOVE
                and scene_point is not None
                and not coverage_contains(
                    selected_pixels.scene_contribution,
                    scene_point,
                )
            ):
                return self._denied(
                    operation,
                    EditorOperationDenial.POINTER_OUTSIDE_SELECTION,
                    scene_id=scene.scene_id,
                    layer_id=selected_pixels.layer.layer_id,
                )
            return self._geometry_allowed(
                operation,
                EditorOperationTarget.SELECTED_PIXELS,
                scene.scene_id,
                selected_pixels.layer.layer_id,
                selected_pixels=selected_pixels,
            )
        pixel_selection_active = (
            self._pixel_selection.state(scene.scene_id).coverage is not None
        )
        if operation is EditorOperation.TRANSFORM and (
            target_preference is EditorOperationTarget.SELECTED_PIXELS
            or pixel_selection_active
        ):
            if not self._capability_allowed(
                self._geometry_capability(
                    operation,
                    EditorOperationTarget.SELECTED_PIXELS,
                )
            ):
                return self._denied(
                    operation,
                    EditorOperationDenial.HOST_POLICY_DENIED,
                    scene_id=scene.scene_id,
                    layer_id=None if selected is None else selected.layer_id,
                )
            return self._denied(
                operation,
                EditorOperationDenial.NO_SELECTED_PIXELS,
                scene_id=scene.scene_id,
                layer_id=None if selected is None else selected.layer_id,
            )
        return self._resolve_layer_geometry(
            operation,
            scene,
            candidate_layer_id,
        )

    def _resolve_layer_geometry(
        self,
        operation: EditorOperation,
        scene: SceneDescriptor,
        candidate_layer_id: uuid.UUID | None,
    ) -> EditorOperationResolution:
        """Resolve one whole-layer geometry target through policy and bounds."""
        layer = (
            self._layer_by_id(scene, candidate_layer_id)
            if candidate_layer_id is not None
            else self._selected_layer(scene)
        )
        if layer is None:
            return self._denied(
                operation,
                EditorOperationDenial.NO_SELECTED_LAYER,
                scene_id=scene.scene_id,
            )
        if not layer.interaction.selectable:
            return self._denied(
                operation,
                EditorOperationDenial.LAYER_NOT_SELECTABLE,
                scene_id=scene.scene_id,
                layer_id=layer.layer_id,
            )
        if not layer.interaction.movable:
            return self._denied(
                operation,
                EditorOperationDenial.LAYER_NOT_MOVABLE,
                scene_id=scene.scene_id,
                layer_id=layer.layer_id,
            )
        if layer.transform is None or not layer.transform.is_invertible:
            return self._denied(
                operation,
                EditorOperationDenial.INVALID_LAYER_GEOMETRY,
                scene_id=scene.scene_id,
                layer_id=layer.layer_id,
            )
        if (
            operation is EditorOperation.TRANSFORM
            and self._layer_geometry.resolved_local_bounds(layer) is None
        ):
            return self._denied(
                operation,
                EditorOperationDenial.NOTHING_TO_TRANSFORM,
                scene_id=scene.scene_id,
                layer_id=layer.layer_id,
            )
        return self._geometry_allowed(
            operation,
            EditorOperationTarget.LAYER,
            scene.scene_id,
            layer.layer_id,
        )

    def _geometry_allowed(
        self,
        operation: EditorOperation,
        target: EditorOperationTarget,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID | None,
        *,
        selected_pixels: SelectedPixelMoveTarget | None = None,
    ) -> EditorOperationResolution:
        """Apply target-specific host capability policy to geometry operations."""
        capability = self._geometry_capability(operation, target)
        if not self._capability_allowed(capability):
            return self._denied(
                operation,
                EditorOperationDenial.HOST_POLICY_DENIED,
                scene_id=scene_id,
                layer_id=layer_id,
            )
        return self._allowed(
            operation,
            target,
            scene_id,
            layer_id,
            selected_pixels=selected_pixels,
        )

    @staticmethod
    def _geometry_capability(
        operation: EditorOperation,
        target: EditorOperationTarget,
    ) -> EditorCapability:
        """Return the one host capability governing a geometry target."""
        if target in {
            EditorOperationTarget.FLOATING_PIXELS,
            EditorOperationTarget.SELECTED_PIXELS,
        }:
            return EditorCapability.EDIT_PIXELS
        if operation is EditorOperation.MOVE:
            return EditorCapability.MOVE_LAYERS
        return EditorCapability.TRANSFORM_LAYERS

    def _resolve_paint(
        self,
        scene: SceneDescriptor,
    ) -> EditorOperationResolution:
        """Resolve direct painting through the registered transaction owner."""
        if not self._capability_allowed(EditorCapability.PAINT):
            return self._denied(
                EditorOperation.PAINT,
                EditorOperationDenial.HOST_POLICY_DENIED,
                scene_id=scene.scene_id,
            )
        active_target = self._active_paint_target()
        if (
            active_target is not None
            and active_target.scene_id == scene.scene_id
            and active_target.kind is PaintTargetKind.PIXEL_SELECTION
        ):
            return self._allowed(
                EditorOperation.PAINT,
                EditorOperationTarget.PIXEL_SELECTION,
                scene.scene_id,
                None,
            )
        layer = self._selected_layer(scene)
        if layer is None:
            if self._default_paint_target_available():
                return self._allowed(
                    EditorOperation.PAINT,
                    EditorOperationTarget.DEFAULT_PAINT_TARGET,
                    scene.scene_id,
                    None,
                )
            return self._denied(
                EditorOperation.PAINT,
                EditorOperationDenial.NO_SELECTED_LAYER,
                scene_id=scene.scene_id,
            )
        target = PaintTargetContext(
            PaintTargetIdentity(scene.scene_id, layer.layer_id),
            scene,
            layer,
        )
        if not self._paint_target_supported(target):
            return self._unsupported_direct_edit(EditorOperation.PAINT, scene, layer)
        if not layer.interaction.pixel_editable:
            return self._denied(
                EditorOperation.PAINT,
                EditorOperationDenial.HOST_POLICY_DENIED,
                scene_id=scene.scene_id,
                layer_id=layer.layer_id,
            )
        return self._allowed(
            EditorOperation.PAINT,
            EditorOperationTarget.LAYER,
            scene.scene_id,
            layer.layer_id,
        )

    def _resolve_delete(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
    ) -> EditorOperationResolution:
        """Resolve selection-constrained clearing through the pixel owner."""
        if not self._capability_allowed(EditorCapability.EDIT_PIXELS):
            return self._denied(
                EditorOperation.DELETE_PIXELS,
                EditorOperationDenial.HOST_POLICY_DENIED,
                scene_id=scene.scene_id,
                layer_id=layer.layer_id,
            )
        if self._pixel_selection.state(scene.scene_id).coverage is None:
            return self._denied(
                EditorOperation.DELETE_PIXELS,
                EditorOperationDenial.NO_PIXEL_SELECTION,
                scene_id=scene.scene_id,
                layer_id=layer.layer_id,
            )
        if self._pixel_owners.owner_for(scene, layer) is None:
            return self._unsupported_direct_edit(
                EditorOperation.DELETE_PIXELS,
                scene,
                layer,
            )
        if not layer.interaction.pixel_editable:
            return self._denied(
                EditorOperation.DELETE_PIXELS,
                EditorOperationDenial.HOST_POLICY_DENIED,
                scene_id=scene.scene_id,
                layer_id=layer.layer_id,
            )
        return self._allowed(
            EditorOperation.DELETE_PIXELS,
            EditorOperationTarget.SELECTED_PIXELS,
            scene.scene_id,
            layer.layer_id,
        )

    def _unsupported_direct_edit(
        self,
        operation: EditorOperation,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
    ) -> EditorOperationResolution:
        """Return source-owned explicit alternatives for immutable content."""
        operations = self._source_operations.operations_for(layer.source)
        alternatives = [EditorOperationAlternative.NEW_RASTER_LAYER]
        if operations.rasterize:
            alternatives.insert(0, EditorOperationAlternative.RASTERIZE)
        if operations.edit_contents:
            alternatives.insert(0, EditorOperationAlternative.EDIT_CONTENTS)
        return self._denied(
            operation,
            EditorOperationDenial.DIRECT_PIXEL_EDIT_UNSUPPORTED,
            scene_id=scene.scene_id,
            layer_id=layer.layer_id,
            alternatives=tuple(alternatives),
        )

    def _selected_layer(self, scene: SceneDescriptor) -> LayerDescriptor | None:
        """Resolve authoritative selection only within the active scene."""
        selected = self._layer_selection.current
        if selected is None or selected.scene_id != scene.scene_id:
            return None
        resolved = self._scene_mutations.find_layer(
            lambda layer: (
                layer.scene_id == selected.scene_id
                and layer.layer_id == selected.layer_id
            )
        )
        return None if resolved is None else resolved[1]

    @staticmethod
    def _layer_by_id(
        scene: SceneDescriptor,
        layer_id: uuid.UUID,
    ) -> LayerDescriptor | None:
        """Return one candidate layer from the already resolved active scene."""
        return next(
            (layer for layer in scene.layers if layer.layer_id == layer_id),
            None,
        )

    @staticmethod
    def _allowed(
        operation: EditorOperation,
        target: EditorOperationTarget,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID | None,
        *,
        selected_pixels: SelectedPixelMoveTarget | None = None,
    ) -> EditorOperationResolution:
        """Build one successful immutable resolution."""
        return EditorOperationResolution(
            operation,
            True,
            target,
            scene_id,
            layer_id,
            selected_pixels=selected_pixels,
        )

    @staticmethod
    def _denied(
        operation: EditorOperation,
        denial: EditorOperationDenial,
        *,
        scene_id: uuid.UUID | None = None,
        layer_id: uuid.UUID | None = None,
        alternatives: tuple[EditorOperationAlternative, ...] = (),
    ) -> EditorOperationResolution:
        """Build one denied immutable resolution."""
        return EditorOperationResolution(
            operation,
            False,
            scene_id=scene_id,
            layer_id=layer_id,
            denial=denial,
            alternatives=alternatives,
        )
