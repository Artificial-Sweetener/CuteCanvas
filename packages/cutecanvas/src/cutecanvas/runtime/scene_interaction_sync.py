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

"""Synchronize transient editor interactions to an authoritative scene."""

from __future__ import annotations

from cutecanvas.editor.affine_interactions import EditorAffineInteractions
from cutecanvas.editor.movement import EditorMovementInteraction
from cutecanvas.scene.layer_move import SceneLayerMoveController
from cutecanvas.scene.transform_session import SceneLayerTransformController
from cutecanvas.snapping.system import SnappingSubsystem
from qpane.sdk.scene import SceneDescriptor


def synchronize_scene_interactions(
    scene: SceneDescriptor | None,
    *,
    movement_interaction: EditorMovementInteraction | None,
    snapping: SnappingSubsystem | None,
    movement: SceneLayerMoveController | None,
    transform: SceneLayerTransformController | None,
    affine: EditorAffineInteractions | None,
) -> None:
    """Clear or reconcile every transient geometry owner for ``scene``."""
    if movement_interaction is not None:
        movement_interaction.synchronize_context()
    if snapping is not None:
        snapping.clear_interactions()
    if movement is not None:
        movement.synchronize_scene(scene)
    if transform is not None:
        transform.synchronize_scene(scene)
    if affine is not None:
        affine.synchronize_scene(scene)


__all__ = ["synchronize_scene_interactions"]
