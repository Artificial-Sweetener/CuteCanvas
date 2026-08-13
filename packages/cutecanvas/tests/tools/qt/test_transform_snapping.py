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

"""Mounted Transform-tool snapping through preview, commit, and history."""

from __future__ import annotations

import uuid

import pytest
from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QTransform
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cutecanvas import CompositionHandle, CuteCanvas, EditorTransformTarget
from qpane.sdk.scene import TransformHandle


def _image() -> QImage:
    """Return a deterministic opaque 100-by-100 layer source."""
    image = QImage(100, 100, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0xFF4FA3D1)
    return image


def _wide_image() -> QImage:
    """Return 100 opaque pixels inside wider transparent editable storage."""
    image = QImage(300, 100, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.fillRect(QRect(0, 0, 100, 100), QColor(79, 163, 209, 255))
    painter.end()
    return image


def _panel_point(canvas: CuteCanvas, scene_point: QPointF) -> QPointF:
    """Project one scene point through the mounted viewport."""
    point = canvas.view().scene_to_panel_point(scene_point)
    assert point is not None
    return point


def _mounted_layers(
    qapp,
    moving_source: QImage | None = None,
) -> tuple[CuteCanvas, CompositionHandle, uuid.UUID, uuid.UUID]:
    """Mount one moving layer and one stationary snap target."""
    canvas = CuteCanvas(features=())
    canvas.resize(800, 800)
    canvas.show()
    document = canvas.editor.compositions.create(
        QRectF(0.0, 0.0, 600.0, 600.0), title="Transform snapping"
    )
    moving_id = canvas.addEditableRasterLayer(moving_source or _image(), label="Moving")
    target_id = canvas.addEditableRasterLayer(_image(), label="Target")
    assert moving_id is not None and target_id is not None
    target = document.layer(target_id)
    assert target is not None
    assert target.set_transform(QTransform.fromTranslate(200.0, 0.0))
    assert canvas.setSelectedLayer(document.id, moving_id)
    canvas.setZoom1To1()
    qapp.processEvents()
    assert canvas.activateEditorTransform(EditorTransformTarget.LAYER_CONTENT)
    qapp.processEvents()
    return canvas, document, moving_id, target_id


def test_resize_handle_snaps_preview_and_committed_layer_to_target_edge(qapp) -> None:
    """Mounted resize feedback and durable history should share exact geometry."""
    canvas, document, moving_id, _target_id = _mounted_layers(qapp)
    try:
        presentation = canvas.sceneLayerTransformInteraction().presentation()
        assert presentation is not None
        right_handle = dict(presentation.handles)[TransformHandle.RIGHT]
        near_target = _panel_point(canvas, QPointF(197.0, 50.0))

        QTest.mousePress(
            canvas,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ShiftModifier,
            right_handle.toPoint(),
        )
        QTest.mouseMove(canvas, near_target.toPoint(), delay=0)
        qapp.processEvents()

        preview = canvas.editorTransformState(EditorTransformTarget.LAYER_CONTENT)
        assert preview.corners is not None
        assert preview.corners[1].x() == 200.0
        assert preview.corners[2].x() == 200.0
        assert tuple(guide.position for guide in canvas.snappingSubsystem().guides) == (
            200.0,
        )

        QTest.mouseRelease(
            canvas,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ShiftModifier,
            near_target.toPoint(),
        )
        qapp.processEvents()
        assert canvas.snappingSubsystem().guides == ()
        assert canvas.applyEditorTransform()

        committed = document.layer(moving_id)
        assert committed is not None
        assert committed.state.transform.m11() == 2.0
        assert committed.state.transform.m22() == 1.0
        assert canvas.undoSceneEdit()
        assert committed.state.transform.m11() == 1.0
        assert canvas.redoSceneEdit()
        assert committed.state.transform.m11() == 2.0
    finally:
        canvas.close()


def test_transform_interior_move_uses_the_same_adjacent_edge_snap(qapp) -> None:
    """Moving inside a transform frame should match the dedicated Move tool."""
    canvas, document, moving_id, _target_id = _mounted_layers(qapp)
    try:
        presentation = canvas.sceneLayerTransformInteraction().presentation()
        assert presentation is not None
        origin = presentation.center
        near_adjacent = _panel_point(canvas, QPointF(147.0, 50.0))

        QTest.mousePress(
            canvas,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            origin.toPoint(),
        )
        QTest.mouseMove(canvas, near_adjacent.toPoint(), delay=0)
        QTest.mouseRelease(
            canvas,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            near_adjacent.toPoint(),
        )
        qapp.processEvents()

        preview = canvas.editorTransformState(EditorTransformTarget.LAYER_CONTENT)
        assert preview.corners is not None
        assert preview.corners[0] == QPointF(100.0, 0.0)
        assert preview.corners[2] == QPointF(200.0, 100.0)
        assert canvas.snappingSubsystem().guides == ()
        assert canvas.applyEditorTransform()
        committed = document.layer(moving_id)
        assert committed is not None
        assert committed.state.transform.dx() == 100.0
    finally:
        canvas.close()


def test_selected_pixel_resize_uses_layer_targets_and_cleans_feedback(qapp) -> None:
    """Selection-content transforms should share targets without self-snapping."""
    canvas, document, moving_id, _target_id = _mounted_layers(qapp, _wide_image())
    try:
        selection = QImage(100, 100, QImage.Format.Format_Grayscale8)
        selection.fill(255)
        assert canvas.setPixelSelection(selection, QRect(0, 0, 100, 100))
        assert canvas.activateEditorTransform(EditorTransformTarget.SELECTION_CONTENT)
        qapp.processEvents()
        presentation = canvas.sceneLayerTransformInteraction().presentation()
        assert presentation is not None
        right_handle = dict(presentation.handles)[TransformHandle.RIGHT]
        near_target = _panel_point(canvas, QPointF(197.0, 50.0))

        QTest.mousePress(
            canvas,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ShiftModifier,
            right_handle.toPoint(),
        )
        QTest.mouseMove(canvas, near_target.toPoint(), delay=0)
        qapp.processEvents()
        preview = canvas.editorTransformState(EditorTransformTarget.SELECTION_CONTENT)
        assert preview.corners is not None
        assert preview.corners[1].x() == 200.0
        assert preview.corners[2].x() == 200.0

        QTest.mouseRelease(
            canvas,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ShiftModifier,
            near_target.toPoint(),
        )
        qapp.processEvents()
        assert canvas.snappingSubsystem().guides == ()
        assert canvas.applyEditorTransform()
        assert canvas.layerLocalBounds(document.id, moving_id) == QRectF(
            0.0, 0.0, 200.0, 100.0
        )
        assert canvas.undoSceneEdit()
        assert canvas.layerLocalBounds(document.id, moving_id) == QRectF(
            0.0, 0.0, 100.0, 100.0
        )
        assert canvas.redoSceneEdit()
        assert canvas.layerLocalBounds(document.id, moving_id) == QRectF(
            0.0, 0.0, 200.0, 100.0
        )
    finally:
        canvas.close()


def test_document_switch_clears_scale_session_and_smart_guides(qapp) -> None:
    """A scene replacement must discard transform snapping from the old owner."""
    canvas, _document, _moving_id, _target_id = _mounted_layers(qapp)
    try:
        presentation = canvas.sceneLayerTransformInteraction().presentation()
        assert presentation is not None
        right_handle = dict(presentation.handles)[TransformHandle.RIGHT]
        near_target = _panel_point(canvas, QPointF(197.0, 50.0))
        QTest.mousePress(
            canvas,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ShiftModifier,
            right_handle.toPoint(),
        )
        QTest.mouseMove(canvas, near_target.toPoint(), delay=0)
        qapp.processEvents()
        assert canvas.snappingSubsystem().guides

        replacement = canvas.editor.compositions.create(
            QRectF(0.0, 0.0, 300.0, 300.0), title="Replacement"
        )
        qapp.processEvents()

        assert replacement.is_open
        assert canvas.snappingSubsystem().guides == ()
        assert not canvas.snappingSubsystem().transform.active
        state = canvas.editorTransformState(EditorTransformTarget.LAYER_CONTENT)
        assert not state.allowed
    finally:
        canvas.close()


def test_cumulative_selection_scale_never_snaps_to_its_original_selection(
    qapp: QApplication,
) -> None:
    """Later gestures must exclude the selected-pixel target's durable bounds."""
    canvas, _document, _moving_id, _target_id = _mounted_layers(qapp, _wide_image())
    try:
        selection = QImage(100, 100, QImage.Format.Format_Grayscale8)
        selection.fill(255)
        assert canvas.setPixelSelection(selection, QRect(0, 0, 100, 100))
        assert canvas.activateEditorTransform(EditorTransformTarget.SELECTION_CONTENT)
        assert canvas.configureSnapping(canvas=False, layers=True, selections=True)
        qapp.processEvents()

        presentation = canvas.sceneLayerTransformInteraction().presentation()
        assert presentation is not None
        right_handle = dict(presentation.handles)[TransformHandle.RIGHT]
        first_endpoint = _panel_point(canvas, QPointF(140.0, 50.0))
        QTest.mousePress(
            canvas,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ShiftModifier,
            right_handle.toPoint(),
        )
        QTest.mouseMove(canvas, first_endpoint.toPoint(), delay=0)
        QTest.mouseRelease(
            canvas,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ShiftModifier,
            first_endpoint.toPoint(),
        )
        qapp.processEvents()

        presentation = canvas.sceneLayerTransformInteraction().presentation()
        assert presentation is not None
        right_handle = dict(presentation.handles)[TransformHandle.RIGHT]
        second_endpoint = _panel_point(canvas, QPointF(103.0, 50.0))
        QTest.mousePress(
            canvas,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ShiftModifier,
            right_handle.toPoint(),
        )
        QTest.mouseMove(canvas, second_endpoint.toPoint(), delay=0)
        qapp.processEvents()

        state = canvas.editorTransformState(EditorTransformTarget.SELECTION_CONTENT)
        assert state.corners is not None
        assert state.corners[1].x() == pytest.approx(103.0)
        assert state.corners[2].x() == pytest.approx(103.0)
        assert canvas.snappingSubsystem().guides == ()
    finally:
        canvas.cancelEditorTransform()
        canvas.close()
