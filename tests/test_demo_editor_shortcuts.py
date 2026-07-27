#    QPane + CuteCanvas - High-performance PySide6 rendering and editing
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
"""Mounted demo checks for window-scoped editor shortcuts."""

from __future__ import annotations

import time

import numpy as np
from cutecanvas import CuteCanvas
from cutecanvas.resources import ProjectResourceReference
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionToolButton, QWidget
from qpane.raster.image_conversion import qimage_to_numpy_argb32

from examples.cutecanvas_demo import ExampleOptions, ExampleWindow
from examples.demonstration.editor_controls import _CenteredMenuToolButton
from tests.harness.timing import (
    absolute_latency_assertions_are_isolated,
    interaction_clock,
)


def _white_image(size: int) -> QImage:
    """Return an opaque square image for one demo composition."""
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(QColor(255, 255, 255))
    return image


def test_demo_selection_split_button_centers_label_across_toolbar(
    qapp: QApplication,
) -> None:
    """Selection text should center across the split control, not its left half."""
    window = ExampleWindow(ExampleOptions())
    try:
        window.resize(900, 600)
        window.show()
        qapp.processEvents()
        assert window.commands.toolbar is not None
        button = window.commands.toolbar.findChild(_CenteredMenuToolButton)
        assert button is not None
        option = QStyleOptionToolButton()
        button.initStyleOption(option)
        native_hint = super(_CenteredMenuToolButton, button).sizeHint()
        indicator_width = button.style().pixelMetric(
            QStyle.PixelMetric.PM_MenuButtonIndicator,
            option,
            button,
        )
        button_center = button.mapTo(
            window.commands.toolbar,
            button.rect().center(),
        ).x()

        assert button._label_rect() == button.rect()
        assert button._label_rect().center() == button.rect().center()
        assert button.sizeHint().width() == native_hint.width() + indicator_width
        assert abs(button_center - window.commands.toolbar.rect().center().x()) <= 1
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def _send_mouse(
    target: QWidget,
    event_type: QEvent.Type,
    point: QPoint,
    *,
    button: Qt.MouseButton,
    buttons: Qt.MouseButton,
) -> None:
    """Deliver one physical-style mouse sample with explicit button state."""
    local = QPointF(point)
    event = QMouseEvent(
        event_type,
        local,
        local,
        QPointF(target.mapToGlobal(point)),
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
        Qt.MouseEventSource.MouseEventNotSynthesized,
    )
    QApplication.sendEvent(target, event)


def _rgb_distance(left: QColor, right: QColor) -> int:
    """Return the summed RGB channel distance between two rendered pixels."""
    return sum(
        abs(left_channel - right_channel)
        for left_channel, right_channel in zip(
            left.getRgb()[:3],
            right.getRgb()[:3],
        )
    )


def _wait_for_pixel_change(
    qapp: QApplication,
    target: QWidget,
    point: QPoint,
    baseline: QColor,
    *,
    timeout_ms: float,
) -> float | None:
    """Return visual-feedback latency once a rendered pixel visibly changes."""
    started = time.perf_counter()
    deadline = started + timeout_ms / 1000.0
    while time.perf_counter() < deadline:
        qapp.processEvents()
        rendered = target.grab().toImage().pixelColor(point)
        if _rgb_distance(rendered, baseline) > 15:
            return (time.perf_counter() - started) * 1000.0
        QTest.qWait(1)
    return None


def test_demo_delete_shortcut_clears_selected_pixels_from_moved_mask(
    qapp: QApplication,
) -> None:
    """Delete must route through the demo action to the selected mask layer."""
    size = 400
    window = ExampleWindow(ExampleOptions())
    try:
        composition_id = window.qpane.createCompositionFromImage(
            _white_image(size),
            title="Delete workflow",
        )
        mask_id = window.qpane.createBlankMask(QSize(size, size))
        assert mask_id is not None
        assert window.qpane.setActiveMaskID(mask_id)
        window.tools.editor_controls.layer_policy.reconcile()
        info = window.qpane.listMasksForComposition(composition_id)[0]
        assert info.scene_id is not None
        assert info.layer_id is not None
        layer = window.qpane.mask_service.assets.get_layer(mask_id)
        assert layer is not None

        def paint_band(pixels: np.ndarray, _image: QImage) -> None:
            """Paint deterministic content across selected and unselected regions."""
            pixels[180:220, 20:360] = 255

        layer.coverage.raster.mutate(paint_band)
        window.qpane.invalidateActiveMaskCache()
        window.qpane.markDirty()
        assert window.qpane.setLayerPlacement(
            info.scene_id,
            info.layer_id,
            QRectF(80.0, 0.0, float(size), float(size)),
        )
        before = layer.coverage.raster.snapshot_array()
        selection = QImage(180, 100, QImage.Format_Grayscale8)
        selection.fill(255)
        assert window.qpane.setPixelSelection(selection, QRect(100, 150, 180, 100))

        window.resize(900, 650)
        window.show()
        window.activateWindow()
        window.qpane.setFocus(Qt.FocusReason.OtherFocusReason)
        qapp.processEvents()
        QTest.keyClick(window.qpane, Qt.Key_Delete)
        qapp.processEvents()

        after = layer.coverage.raster.snapshot_array()
        assert not np.any(after[180:220, 20:200])
        assert np.array_equal(after[:, 201:], before[:, 201:])
        assert window.qpane.sceneEditUndoAvailable()
        assert "Cleared selected pixels" in window.status.currentMessage()
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_demo_first_mask_stroke_is_immediate_and_ctrl_z_undoes(
    qapp: QApplication,
) -> None:
    """The literal first-stroke demo workflow must enable and execute Ctrl+Z."""
    window = ExampleWindow(ExampleOptions())
    try:
        image = QImage(QSize(3440, 1440), QImage.Format_ARGB32)
        image.fill(QColor(35, 55, 80))
        window.qpane.createCompositionFromImage(
            image,
            title="First stroke",
        )
        window.resize(2048, 900)
        window.show()
        window.activateWindow()
        qapp.processEvents()
        mask_id = window.workspace.create_mask_for_current_image()
        assert mask_id is not None
        window.tools.set_mode(CuteCanvas.CONTROL_MODE_DRAW_BRUSH)
        window.qpane.setBrushSize(120)
        window.qpane.setFocus(Qt.FocusReason.OtherFocusReason)
        qapp.processEvents()
        layer = window.qpane.mask_service.assets.get_layer(mask_id)
        assert layer is not None
        assert not layer.coverage.raster.snapshot_array().any()
        center = window.qpane.rect().center()
        end = center + QPoint(180, 0)

        dispatch_ms: list[float] = []
        feedback_ms: list[float] = []
        initial_frame = window.qpane.grab().toImage()
        before_contact = initial_frame.pixelColor(center)
        started = interaction_clock()
        _send_mouse(
            window.qpane,
            QEvent.Type.MouseButtonPress,
            center,
            button=Qt.MouseButton.LeftButton,
            buttons=Qt.MouseButton.LeftButton,
        )
        dispatch_ms.append((interaction_clock() - started) * 1000.0)
        isolated_latency = absolute_latency_assertions_are_isolated()
        feedback_timeout_ms = 100.0 if isolated_latency else 1000.0
        contact_feedback = _wait_for_pixel_change(
            qapp,
            window.qpane,
            center,
            before_contact,
            timeout_ms=feedback_timeout_ms,
        )
        if contact_feedback is not None:
            feedback_ms.append(contact_feedback)
        before_motion = window.qpane.grab().toImage().pixelColor(end)
        started = interaction_clock()
        _send_mouse(
            window.qpane,
            QEvent.Type.MouseMove,
            end,
            button=Qt.MouseButton.NoButton,
            buttons=Qt.MouseButton.LeftButton,
        )
        dispatch_ms.append((interaction_clock() - started) * 1000.0)
        motion_feedback = _wait_for_pixel_change(
            qapp,
            window.qpane,
            end,
            before_motion,
            timeout_ms=feedback_timeout_ms,
        )
        if motion_feedback is not None:
            feedback_ms.append(motion_feedback)
        release_started = interaction_clock()
        _send_mouse(
            window.qpane,
            QEvent.Type.MouseButtonRelease,
            end,
            button=Qt.MouseButton.LeftButton,
            buttons=Qt.MouseButton.NoButton,
        )
        dispatch_ms.append((interaction_clock() - release_started) * 1000.0)

        deadline = time.perf_counter() + 3.0
        while (
            time.perf_counter() < deadline
            and layer.coverage.raster.content_bounds() is None
        ):
            qapp.processEvents()
            QTest.qWait(1)
        commit_ms = (interaction_clock() - release_started) * 1000.0
        assert layer.coverage.raster.content_bounds() is not None
        assert window.qpane.sceneEditUndoAvailable()
        assert len(feedback_ms) == 2
        if isolated_latency:
            assert max(feedback_ms) < 100.0
            assert max(dispatch_ms) < 100.0
            assert commit_ms < 100.0
        assert window.tools.editor_controls.undo_action.isEnabled()
        assert (
            _rgb_distance(
                window.qpane.grab().toImage().pixelColor(center),
                before_contact,
            )
            > 15
        )

        QTest.keyClick(window.qpane, Qt.Key_Z, Qt.ControlModifier)
        deadline = time.perf_counter() + 3.0
        while (
            time.perf_counter() < deadline
            and layer.coverage.raster.snapshot_array().any()
        ):
            qapp.processEvents()
            QTest.qWait(1)
        assert not layer.coverage.raster.snapshot_array().any()
        deadline = time.perf_counter() + 0.1
        while time.perf_counter() < deadline:
            qapp.processEvents()
            restored = window.qpane.grab().toImage().pixelColor(center)
            if _rgb_distance(restored, before_contact) <= 5:
                break
            QTest.qWait(1)
        assert _rgb_distance(restored, before_contact) <= 5
        assert window.tools.editor_controls.undo_action.isEnabled()
        assert window.tools.editor_controls.redo_action.isEnabled()
        assert "Undid the last editor change" in window.status.currentMessage()
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_demo_ctrl_d_deselects_while_escape_preserves_committed_selection(
    qapp: QApplication,
) -> None:
    """Deselect must not conflate durable state with cancellation."""
    window = ExampleWindow(ExampleOptions())
    try:
        window.qpane.createCompositionFromImage(
            _white_image(200),
            title="Selection dismissal",
        )
        selection = QImage(80, 60, QImage.Format_Grayscale8)
        selection.fill(255)
        assert window.qpane.setPixelSelection(selection, QRect(20, 30, 80, 60))
        window.show()
        window.activateWindow()
        window.qpane.setFocus(Qt.FocusReason.OtherFocusReason)
        qapp.processEvents()

        QTest.keyClick(window.qpane, Qt.Key_Escape)
        qapp.processEvents()
        assert window.qpane.pixelSelectionState().has_selection

        QTest.keyClick(window.qpane, Qt.Key_D, Qt.ControlModifier)
        qapp.processEvents()
        assert not window.qpane.pixelSelectionState().has_selection
        assert "Selection cleared" in window.status.currentMessage()
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_demo_repeated_ctrl_z_replays_committed_raster_move_chronologically(
    qapp: QApplication,
) -> None:
    """Repeated Undo must traverse deselection, movement, and prior selection."""
    window = ExampleWindow(ExampleOptions())
    try:
        window.qpane.createCompositionFromImage(
            _white_image(400),
            title="Raster movement",
        )
        image = QImage(200, 200, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        for y in range(40, 80):
            for x in range(40, 80):
                image.setPixelColor(x, y, QColor(230, 60, 40, 255))
        layer_id = window.qpane.addEditableRasterLayer(
            image,
            placement=QRectF(120.0, 120.0, 200.0, 200.0),
        )
        assert layer_id is not None
        scene = window.qpane.currentScene()
        assert scene is not None
        assert window.qpane.setSelectedLayer(scene.scene_id, layer_id)
        composition_id = window.qpane.currentCompositionID()
        assert composition_id is not None
        initial_history_depth = len(
            window.qpane.compositionService().edit_controller.undo_commands(
                composition_id
            )
        )
        selection = QImage(40, 40, QImage.Format_Grayscale8)
        selection.fill(255)
        assert window.qpane.setPixelSelection(selection, QRect(160, 160, 40, 40))
        window.resize(800, 620)
        window.show()
        window.activateWindow()
        window.qpane.setFocus(Qt.FocusReason.OtherFocusReason)
        qapp.processEvents()
        window.tools.set_mode(CuteCanvas.CONTROL_MODE_MOVE)
        qapp.processEvents()
        resolved_scene_id = window.qpane._resolve_public_scene_id(scene.scene_id)
        source = window.qpane.view().layer_source_to_panel_point(
            resolved_scene_id,
            layer_id,
            QPointF(60.0, 60.0),
        )
        destination = window.qpane.view().layer_source_to_panel_point(
            resolved_scene_id,
            layer_id,
            QPointF(100.0, 60.0),
        )
        assert source is not None
        assert destination is not None

        QTest.mousePress(window.qpane, Qt.LeftButton, Qt.NoModifier, source.toPoint())
        qapp.processEvents()
        QTest.mouseMove(window.qpane, destination.toPoint(), delay=0)
        qapp.processEvents()
        QTest.mouseRelease(
            window.qpane,
            Qt.LeftButton,
            Qt.NoModifier,
            destination.toPoint(),
        )
        qapp.processEvents()
        floating_state = window.qpane.floatingPixelEditState()
        assert floating_state is not None
        moved_x = 60 + floating_state.offset.x()
        moved_y = 60 + floating_state.offset.y()
        assert moved_x != 60
        assert window.tools.editor_controls.undo_action.isEnabled()
        QTest.keyClick(window.qpane, Qt.Key_D, Qt.ControlModifier)
        qapp.processEvents()
        assert window.qpane.floatingPixelEditState() is None
        assert not window.qpane.pixelSelectionState().has_selection
        assert window.tools.editor_controls.undo_action.isEnabled()
        layer_instance = window.qpane.compositionService().layers.layer(
            composition_id,
            layer_id,
        )
        assert layer_instance is not None
        assert isinstance(layer_instance.source, ProjectResourceReference)
        asset = window.qpane._editable_raster_assets.get(
            layer_instance.source.resource_id
        )
        assert asset is not None
        committed_pixels = qimage_to_numpy_argb32(asset.surface.presentation_qimage())
        committed_rows, committed_columns = np.nonzero(committed_pixels[:, :, 3])
        assert (int(committed_columns.min()), int(committed_columns.max())) == (
            40 + floating_state.offset.x(),
            79 + floating_state.offset.x(),
        )
        assert (int(committed_rows.min()), int(committed_rows.max())) == (
            40 + floating_state.offset.y(),
            79 + floating_state.offset.y(),
        )
        assert asset.surface.presentation_qimage().pixelColor(
            moved_x, moved_y
        ) == QColor(
            230,
            60,
            40,
            255,
        )

        QTest.keyClick(window.qpane, Qt.Key_Z, Qt.ControlModifier)
        qapp.processEvents()
        assert window.qpane.pixelSelectionState().has_selection
        assert asset.surface.presentation_qimage().pixelColor(
            moved_x, moved_y
        ) == QColor(
            230,
            60,
            40,
            255,
        )
        assert window.tools.editor_controls.undo_action.isEnabled()
        assert window.tools.editor_controls.redo_action.isEnabled()

        QTest.keyClick(window.qpane, Qt.Key_Z, Qt.ControlModifier)
        qapp.processEvents()
        assert asset.surface.presentation_qimage().pixelColor(60, 60) == QColor(
            230,
            60,
            40,
            255,
        )
        assert (
            asset.surface.presentation_qimage().pixelColor(moved_x, moved_y).alpha()
            == 0
        )

        QTest.keyClick(window.qpane, Qt.Key_Z, Qt.ControlModifier)
        qapp.processEvents()
        assert not window.qpane.pixelSelectionState().has_selection
        assert (
            len(
                window.qpane.compositionService().edit_controller.undo_commands(
                    composition_id
                )
            )
            == initial_history_depth
        )
        assert window.tools.editor_controls.undo_action.isEnabled()
        assert window.tools.editor_controls.redo_action.isEnabled()
        assert any(
            layer.layer_id == layer_id for layer in window.qpane.currentScene().layers
        )

        for _step in range(3):
            window.tools.editor_controls.redo_action.trigger()
            qapp.processEvents()

        assert any(
            layer.layer_id == layer_id for layer in window.qpane.currentScene().layers
        )
        assert not window.qpane.pixelSelectionState().has_selection
        assert asset.surface.presentation_qimage().pixelColor(60, 60).alpha() == 0
        assert asset.surface.presentation_qimage().pixelColor(
            moved_x, moved_y
        ) == QColor(
            230,
            60,
            40,
            255,
        )
        assert not window.tools.editor_controls.redo_action.isEnabled()
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_demo_shows_contextual_resolution_controls_for_floating_pixels(
    qapp: QApplication,
    monkeypatch,
) -> None:
    """The demo should expose intentional resolution controls only when needed."""
    size = 240
    window = ExampleWindow(ExampleOptions())
    try:
        window.qpane.createCompositionFromImage(
            _white_image(size),
            title="Floating pixels",
        )
        mask_id = window.qpane.createBlankMask(QSize(size, size))
        assert mask_id is not None
        assert window.qpane.setActiveMaskID(mask_id)
        window.tools.editor_controls.layer_policy.reconcile()
        layer = window.qpane.mask_service.assets.get_layer(mask_id)
        assert layer is not None

        def paint_square(pixels: np.ndarray, _image: QImage) -> None:
            """Create content under the tested selection."""
            pixels[60:100, 60:100] = 255

        layer.coverage.raster.mutate(paint_square)
        window.qpane.invalidateActiveMaskCache()
        selection = QImage(40, 40, QImage.Format_Grayscale8)
        selection.fill(255)
        assert window.qpane.setPixelSelection(selection, QRect(60, 60, 40, 40))
        window.resize(700, 560)
        window.show()
        window.activateWindow()
        qapp.processEvents()
        assert window.commands._floating_pixels_toolbar is not None
        assert not window.commands._floating_pixels_toolbar.isVisible()
        coordinates = window.qpane.activeMaskLayerCoordinates()
        start = coordinates.source_to_panel(QPoint(80, 80))
        finish = coordinates.source_to_panel(QPoint(125, 105))
        assert start is not None
        assert finish is not None
        window.tools.set_mode(CuteCanvas.CONTROL_MODE_MOVE)

        QTest.mousePress(
            window.qpane,
            Qt.LeftButton,
            Qt.NoModifier,
            start.toPoint(),
        )
        QTest.mouseMove(window.qpane, finish.toPoint(), delay=0)
        QTest.mouseRelease(
            window.qpane,
            Qt.LeftButton,
            Qt.NoModifier,
            finish.toPoint(),
        )
        qapp.processEvents()

        assert window.qpane.floatingPixelEditState() is not None
        assert window.commands._floating_pixels_toolbar.isVisible()
        assert window.tools.editor_controls.anchor_floating_action.isEnabled()
        assert window.tools.editor_controls.promote_floating_action.isEnabled()
        floating_before_space = window.qpane.floatingPixelEditState()
        monkeypatch.setattr(
            window.application_input,
            "canvas_under_cursor",
            lambda _pane: True,
        )
        space_press = QKeyEvent(
            QEvent.KeyPress,
            Qt.Key_Space,
            Qt.NoModifier,
        )
        space_release = QKeyEvent(
            QEvent.KeyRelease,
            Qt.Key_Space,
            Qt.NoModifier,
        )
        assert window.application_input.handle_spacebar_event(
            window.commands.toolbar,
            space_press,
        )
        assert window.qpane.getControlMode() == CuteCanvas.CONTROL_MODE_PANZOOM
        assert window.qpane.floatingPixelEditState() == floating_before_space
        assert window.application_input.handle_spacebar_event(
            window.commands.toolbar,
            space_release,
        )
        assert window.qpane.getControlMode() == CuteCanvas.CONTROL_MODE_MOVE
        assert window.qpane.floatingPixelEditState() == floating_before_space
        window.tools.editor_controls.cancel_floating_action.trigger()
        qapp.processEvents()
        assert window.qpane.floatingPixelEditState() is None
        assert not window.commands._floating_pixels_toolbar.isVisible()
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()
