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
"""Public contracts for composable host editor capability policy."""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage

from cutecanvas import (
    EditorCapability,
    EditorIntent,
    EditorPolicy,
    LayerPolicy,
    NonEditablePaintPolicy,
)


def test_noneditable_paint_policy_defaults_to_visible_layer_creation() -> None:
    """Editor policy explicitly controls automatic paint-layer provisioning."""
    assert (
        EditorPolicy().noneditable_paint is NonEditablePaintPolicy.CREATE_RASTER_LAYER
    )
    assert (
        EditorPolicy(noneditable_paint=NonEditablePaintPolicy.REJECT).noneditable_paint
        is NonEditablePaintPolicy.REJECT
    )


def test_editor_capabilities_are_independent_and_queryable(qpane_with_mask) -> None:
    """Host policy must deny only the omitted capability through one resolver."""
    viewer, _assets, image_id = qpane_with_mask
    raster = viewer.activeRasterResolver().resolve()
    assert raster is not None
    mask_id = viewer.createBlankMask(raster.image.size())
    assert mask_id is not None
    assert viewer.setActiveMaskID(mask_id)
    scene = viewer.currentScene()
    assert scene is not None
    mask_layer = next(
        layer
        for layer in scene.layers
        if layer.source_kind == "coverage" and layer.source_id == mask_id
    )
    viewer.setLayerInteractionPolicy(
        scene.scene_id,
        mask_layer.layer_id,
        LayerPolicy(
            selectable=True,
            movable=True,
            pixel_editable=True,
        ),
    )
    viewer.setSelectedLayer(scene.scene_id, mask_layer.layer_id)
    assert viewer.selectedLayer().layer_id == mask_layer.layer_id
    coverage = QImage(4, 4, QImage.Format_Grayscale8)
    coverage.fill(Qt.white)
    assert viewer.setPixelSelection(coverage, QRect(0, 0, 4, 4))
    assert viewer.editorOperationState(EditorIntent.PAINT).allowed
    assert viewer.editorOperationState(EditorIntent.DELETE_PIXELS).allowed
    assert viewer.editorOperationState(EditorIntent.MOVE).allowed

    emitted: list[EditorPolicy] = []
    viewer.editorPolicyChanged.connect(emitted.append)
    selection_only = EditorPolicy(frozenset({EditorCapability.SELECT_PIXELS}))
    assert viewer.setEditorPolicy(selection_only)
    assert emitted == [selection_only]
    assert viewer.editorPolicy() == selection_only
    assert not viewer.editorOperationState(EditorIntent.PAINT).allowed
    assert (
        viewer.editorOperationState(EditorIntent.PAINT).denial == "host-policy-denied"
    )
    assert not viewer.editorOperationState(EditorIntent.DELETE_PIXELS).allowed
    assert not viewer.editorOperationState(EditorIntent.MOVE).allowed
    assert viewer.editorOperationState(EditorIntent.SELECT_PIXELS).allowed
    assert viewer.setPixelSelection(coverage, QRect(1, 1, 4, 4))
    assert viewer.clearPixelSelection()
    assert viewer.maskIDsForComposition(image_id) == [mask_id]


def test_selection_facade_commands_obey_host_policy(qpane_with_mask) -> None:
    """Programmatic selection creation must match selection-tool availability."""
    viewer, _assets, _image_id = qpane_with_mask
    denied = EditorPolicy(frozenset())
    assert viewer.setEditorPolicy(denied)
    coverage = QImage(2, 2, QImage.Format_Grayscale8)
    coverage.fill(Qt.white)

    assert not viewer.setPixelSelection(coverage, QRect(0, 0, 2, 2))
    assert not viewer.selectAllPixels()
    assert not viewer.invertPixelSelection()
    state = viewer.editorOperationState(EditorIntent.SELECT_PIXELS)
    assert not state.allowed
    assert state.denial == "host-policy-denied"
