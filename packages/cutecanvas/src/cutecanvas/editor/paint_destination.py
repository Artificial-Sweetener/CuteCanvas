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
"""Interactive paint-destination validation and visible layer provisioning."""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable

from PySide6.QtCore import QRectF, QSize
from qpane.sdk.scene import LayerInteractionPolicy, SceneDescriptor

from ..painting import PaintingCoordinator
from ..raster.layers import EditableRasterLayerController
from ..scene.layer_selection import SceneLayerSelectionController
from ..types import (
    EditorCapability,
    EditorPolicy,
    NonEditablePaintPolicy,
    RasterExtentPolicy,
)
from .operation_resolution import EditorOperation, EditorOperationResolver


class InteractivePaintDestinationCoordinator:
    """Ensure interactive painting writes only to the visibly selected layer."""

    def __init__(
        self,
        *,
        active_scene: Callable[[], SceneDescriptor | None],
        selection: SceneLayerSelectionController,
        painting: PaintingCoordinator,
        operations: EditorOperationResolver,
        rasters: EditableRasterLayerController,
        policy: Callable[[], EditorPolicy],
        capability_allowed: Callable[[EditorCapability], bool],
        scene_changed: Callable[[], None],
    ) -> None:
        """Bind authoritative selection, policy, layer, and operation owners."""
        self._active_scene = active_scene
        self._selection = selection
        self._painting = painting
        self._operations = operations
        self._rasters = rasters
        self._policy = policy
        self._capability_allowed = capability_allowed
        self._scene_changed = scene_changed

    def can_prepare(self) -> bool:
        """Return whether a stroke can use or visibly provision its destination."""
        if self._operations.resolve(EditorOperation.PAINT).allowed:
            return True
        return self._can_create_layer()

    def prepare(self) -> bool:
        """Resolve the selected layer or create and select an editable one above it."""
        resolution = self._operations.resolve(EditorOperation.PAINT)
        if resolution.allowed:
            return self._select_resolved_layer(resolution.layer_id)
        scene = self._active_scene()
        selected = self._selection.resolve(scene)
        if scene is None or selected is None or not self._can_create_layer():
            return False
        selected_index = next(
            (
                index
                for index, layer in enumerate(scene.layers)
                if layer.layer_id == selected.layer_id
            ),
            None,
        )
        if selected_index is None:
            return False
        size = QSize(
            max(1, math.ceil(scene.bounds.width)),
            max(1, math.ceil(scene.bounds.height)),
        )
        layer_id = self._rasters.add_empty(
            size,
            placement=QRectF(
                scene.bounds.x,
                scene.bounds.y,
                scene.bounds.width,
                scene.bounds.height,
            ),
            interaction=LayerInteractionPolicy(
                selectable=True,
                movable=True,
                pixel_editable=True,
                reorderable=True,
                removable=True,
            ),
            label="Paint Layer",
            extent_policy=RasterExtentPolicy.UNBOUNDED,
            index=selected_index + 1,
        )
        if layer_id is None:
            return False
        self._scene_changed()
        self._selection.select(scene.scene_id, layer_id)
        resolution = self._operations.resolve(EditorOperation.PAINT)
        return resolution.allowed and self._select_resolved_layer(resolution.layer_id)

    def _select_resolved_layer(self, layer_id: uuid.UUID | None) -> bool:
        """Synchronize the paint transaction owner with visible layer selection."""
        if layer_id is None:
            return True
        scene = self._active_scene()
        return bool(
            scene is not None and self._painting.select_layer(scene.scene_id, layer_id)
        )

    def _can_create_layer(self) -> bool:
        """Return whether current policy permits one automatic raster layer."""
        scene = self._active_scene()
        return bool(
            scene is not None
            and self._selection.resolve(scene) is not None
            and self._policy().noneditable_paint
            is NonEditablePaintPolicy.CREATE_RASTER_LAYER
            and self._capability_allowed(EditorCapability.PAINT)
            and self._capability_allowed(EditorCapability.MANAGE_LAYERS)
        )
