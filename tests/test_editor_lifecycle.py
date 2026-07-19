#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Public editor-state lifecycle checks across composition changes."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage

from qpane import QPane


def _image() -> QImage:
    """Return a small opaque catalog image."""
    image = QImage(16, 16, QImage.Format_ARGB32)
    image.fill(Qt.white)
    return image


def _coverage(width: int, height: int, value: int = 255) -> QImage:
    """Return uniform grayscale selection coverage."""
    image = QImage(width, height, QImage.Format_Grayscale8)
    image.fill(value)
    return image


def test_pixel_selection_and_history_follow_scene_lifecycle(qapp) -> None:
    """Switching and removing scenes must isolate and release editor state."""
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    pane = QPane(features=("mask",))
    try:
        pane.setImagesByID(
            QPane.imageMapFromLists(
                [_image(), _image()],
                [None, None],
                [first_id, second_id],
            ),
            first_id,
        )
        assert pane.setPixelSelection(_coverage(5, 6), QRect(1, 2, 5, 6))
        first_state = pane.pixelSelectionState()
        assert first_state is not None
        assert first_state.bounds == QRect(1, 2, 5, 6)
        assert pane.sceneEditUndoAvailable()

        pane.setCurrentImageID(second_id)
        second_empty = pane.pixelSelectionState()
        assert second_empty is not None
        assert not second_empty.has_selection
        assert not pane.sceneEditUndoAvailable()
        assert pane.setPixelSelection(_coverage(3, 4, 128), QRect(7, 8, 3, 4))
        second_state = pane.pixelSelectionState()
        assert second_state is not None
        assert second_state.bounds == QRect(7, 8, 3, 4)

        pane.setCurrentImageID(first_id)
        restored_first = pane.pixelSelectionState()
        assert restored_first is not None
        assert restored_first.bounds == QRect(1, 2, 5, 6)
        assert pane.undoSceneEdit()
        assert not pane.pixelSelectionState().has_selection
        assert pane.redoSceneEdit()
        assert pane.pixelSelectionState().bounds == QRect(1, 2, 5, 6)

        pane.removeImageByID(first_id)
        assert pane.currentImageID() == second_id
        remaining = pane.pixelSelectionState()
        assert remaining is not None
        assert remaining.bounds == QRect(7, 8, 3, 4)
        pane.removeImageByID(second_id)
        assert pane.pixelSelectionState() is None
        assert pane.selectedLayer() is None
        assert not pane.sceneEditUndoAvailable()
    finally:
        pane.clearImages()
        pane.deleteLater()
        qapp.processEvents()
