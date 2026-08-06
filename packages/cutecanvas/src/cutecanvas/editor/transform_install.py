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

"""Construct the affine interaction and its snapping collaborators."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF
from qpane.sdk.scene import SceneDescriptor

from cutecanvas.scene.layer_geometry import LayerGeometryResolver
from cutecanvas.selection import PixelSelectionService
from cutecanvas.snapping.system import SnappingSubsystem

from .operation_resolution import EditorOperationResolver
from .pixel_movement import SelectedPixelMovementController
from .transform_coordinator import EditorTransformCoordinator
from .transform_interaction import SceneLayerTransformInteraction


def create_editor_transform_interaction(
    *,
    active_scene: Callable[[], SceneDescriptor | None],
    geometry: LayerGeometryResolver,
    pixel_selection: PixelSelectionService,
    panel_to_scene: Callable[[QPointF], QPointF | None],
    scene_to_panel: Callable[[QPointF], QPointF | None],
    viewport_zoom: Callable[[], float],
    pixels: SelectedPixelMovementController,
    layers: SceneLayerTransformInteraction,
    operations: EditorOperationResolver,
    preview_changed: Callable[[], None],
    transform_changed: Callable[[], None],
) -> tuple[SnappingSubsystem, EditorTransformCoordinator]:
    """Return one fully connected transform interaction and snapping boundary."""
    snapping = SnappingSubsystem.create(
        active_scene=active_scene,
        geometry=geometry,
        pixel_selection=pixel_selection,
        panel_to_scene=panel_to_scene,
        scene_to_panel=scene_to_panel,
        viewport_zoom=viewport_zoom,
        changed=preview_changed,
    )
    transform = EditorTransformCoordinator(
        pixels=pixels,
        layers=layers,
        operations=operations,
        snapping=snapping.transform,
        changed=transform_changed,
    )
    return snapping, transform


__all__ = ["create_editor_transform_interaction"]
