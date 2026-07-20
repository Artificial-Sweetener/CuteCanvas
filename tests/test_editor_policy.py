#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Public contracts for composable host editor capability policy."""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage

from qpane import (
    EditorCapability,
    EditorIntent,
    QPaneEditorPolicy,
    QPaneLayerInteractionPolicy,
)

pytest_plugins = ("tests.test_mask_workflows",)


def test_editor_capabilities_are_independent_and_queryable(qpane_with_mask) -> None:
    """Host policy must deny only the omitted capability through one resolver."""
    viewer, _assets, image_id = qpane_with_mask
    image = viewer.catalog().currentImage()
    assert image is not None
    mask_id = viewer.createBlankMask(image.size())
    assert mask_id is not None
    assert viewer.setActiveMaskID(mask_id)
    scene = viewer.currentScene()
    assert scene is not None
    mask_layer = next(
        layer
        for layer in scene.layers
        if layer.source_kind == "mask" and layer.source_id == mask_id
    )
    assert viewer.setLayerInteractionPolicy(
        scene.scene_id,
        mask_layer.layer_id,
        QPaneLayerInteractionPolicy(
            selectable=True,
            movable=True,
            pixel_editable=True,
        ),
    )
    assert viewer.setSelectedLayer(scene.scene_id, mask_layer.layer_id)
    coverage = QImage(4, 4, QImage.Format_Grayscale8)
    coverage.fill(Qt.white)
    assert viewer.setPixelSelection(coverage, QRect(0, 0, 4, 4))
    assert viewer.editorOperationState(EditorIntent.PAINT).allowed
    assert viewer.editorOperationState(EditorIntent.DELETE_PIXELS).allowed
    assert viewer.editorOperationState(EditorIntent.MOVE).allowed

    emitted: list[QPaneEditorPolicy] = []
    viewer.editorPolicyChanged.connect(emitted.append)
    selection_only = QPaneEditorPolicy(frozenset({EditorCapability.SELECT_PIXELS}))
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
    assert viewer.maskIDsForImage(image_id) == [mask_id]


def test_selection_facade_commands_obey_host_policy(qpane_with_mask) -> None:
    """Programmatic selection creation must match selection-tool availability."""
    viewer, _assets, _image_id = qpane_with_mask
    denied = QPaneEditorPolicy(frozenset())
    assert viewer.setEditorPolicy(denied)
    coverage = QImage(2, 2, QImage.Format_Grayscale8)
    coverage.fill(Qt.white)

    assert not viewer.setPixelSelection(coverage, QRect(0, 0, 2, 2))
    assert not viewer.selectAllPixels()
    assert not viewer.invertPixelSelection()
    state = viewer.editorOperationState(EditorIntent.SELECT_PIXELS)
    assert not state.allowed
    assert state.denial == "host-policy-denied"
