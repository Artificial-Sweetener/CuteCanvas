#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Mounted demo checks for window-scoped editor shortcuts."""

from __future__ import annotations

import time
import uuid

import numpy as np
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionToolButton, QWidget

from examples.demo import ExampleOptions, ExampleWindow
from examples.demonstration.editor_controls import _CenteredMenuToolButton
from qpane import QPane
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
    window = ExampleWindow(ExampleOptions(feature_set="core"))
    try:
        window.resize(900, 600)
        window.show()
        qapp.processEvents()
        button = window._tools_toolbar.findChild(_CenteredMenuToolButton)
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
            window._tools_toolbar,
            button.rect().center(),
        ).x()

        assert button._label_rect() == button.rect()
        assert button._label_rect().center() == button.rect().center()
        assert button.sizeHint().width() == native_hint.width() + indicator_width
        assert abs(button_center - window._tools_toolbar.rect().center().x()) <= 1
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
    window = ExampleWindow(ExampleOptions(feature_set="mask"))
    try:
        image_id = uuid.uuid4()
        window.qpane.setImagesByID(
            QPane.imageMapFromLists([_white_image(size)], [None], [image_id]),
            image_id,
        )
        mask_id = window.qpane.createBlankMask(window.qpane.currentImage.size())
        assert mask_id is not None
        assert window.qpane.setActiveMaskID(mask_id)
        window.editor_controls.apply_layer_policy()
        info = window.qpane.listMasksForImage()[0]
        assert info.scene_id is not None
        assert info.layer_id is not None
        layer = window.qpane.mask_service.assets.get_layer(mask_id)
        assert layer is not None

        def paint_band(pixels: np.ndarray, _image: QImage) -> None:
            """Paint deterministic content across selected and unselected regions."""
            pixels[180:220, 20:360] = 255

        layer.surface.mutate(paint_band)
        window.qpane.invalidateActiveMaskCache()
        window.qpane.markDirty()
        assert window.qpane.setLayerPlacement(
            info.scene_id,
            info.layer_id,
            QRectF(80.0, 0.0, float(size), float(size)),
        )
        before = layer.surface.snapshot_array()
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

        after = layer.surface.snapshot_array()
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
    window = ExampleWindow(ExampleOptions(feature_set="mask"))
    try:
        image_id = uuid.uuid4()
        image = QImage(QSize(3440, 1440), QImage.Format_ARGB32)
        image.fill(QColor(35, 55, 80))
        window.qpane.setImagesByID(
            QPane.imageMapFromLists([image], [None], [image_id]),
            image_id,
        )
        window.resize(2048, 900)
        window.show()
        window.activateWindow()
        qapp.processEvents()
        mask_id = window._create_mask_for_current_image()
        assert mask_id is not None
        window._set_control_mode(QPane.CONTROL_MODE_DRAW_BRUSH)
        window.qpane.setBrushSize(120)
        window.qpane.setFocus(Qt.FocusReason.OtherFocusReason)
        qapp.processEvents()
        layer = window.qpane.mask_service.assets.get_layer(mask_id)
        assert layer is not None
        assert not layer.surface.snapshot_array().any()
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
        contact_feedback = _wait_for_pixel_change(
            qapp,
            window.qpane,
            center,
            before_contact,
            timeout_ms=100.0,
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
            timeout_ms=100.0,
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
            time.perf_counter() < deadline and not window.qpane.sceneEditUndoAvailable()
        ):
            qapp.processEvents()
            QTest.qWait(1)
        commit_ms = (interaction_clock() - release_started) * 1000.0
        assert window.qpane.sceneEditUndoAvailable()
        assert len(feedback_ms) == 2
        assert max(feedback_ms) < 100.0
        if absolute_latency_assertions_are_isolated():
            assert max(dispatch_ms) < 100.0
            assert commit_ms < 100.0
        assert layer.surface.snapshot_array().any()
        assert window.editor_controls.undo_action.isEnabled()
        assert (
            _rgb_distance(
                window.qpane.grab().toImage().pixelColor(center),
                before_contact,
            )
            > 15
        )

        QTest.keyClick(window.qpane, Qt.Key_Z, Qt.ControlModifier)
        deadline = time.perf_counter() + 3.0
        while time.perf_counter() < deadline and layer.surface.snapshot_array().any():
            qapp.processEvents()
            QTest.qWait(1)
        assert not layer.surface.snapshot_array().any()
        deadline = time.perf_counter() + 0.1
        while time.perf_counter() < deadline:
            qapp.processEvents()
            restored = window.qpane.grab().toImage().pixelColor(center)
            if _rgb_distance(restored, before_contact) <= 5:
                break
            QTest.qWait(1)
        assert _rgb_distance(restored, before_contact) <= 5
        assert not window.editor_controls.undo_action.isEnabled()
        assert window.editor_controls.redo_action.isEnabled()
        assert "Undid the last editor change" in window.status.currentMessage()
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_demo_ctrl_d_deselects_while_escape_preserves_committed_selection(
    qapp: QApplication,
) -> None:
    """Photoshop-style deselect must not conflate durable state with cancellation."""
    window = ExampleWindow(ExampleOptions(feature_set="mask"))
    try:
        image_id = uuid.uuid4()
        window.qpane.setImagesByID(
            QPane.imageMapFromLists([_white_image(200)], [None], [image_id]),
            image_id,
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


def test_demo_shows_contextual_resolution_controls_for_floating_pixels(
    qapp: QApplication,
    monkeypatch,
) -> None:
    """The demo should expose intentional resolution controls only when needed."""
    size = 240
    window = ExampleWindow(ExampleOptions(feature_set="mask"))
    try:
        image_id = uuid.uuid4()
        window.qpane.setImagesByID(
            QPane.imageMapFromLists([_white_image(size)], [None], [image_id]),
            image_id,
        )
        mask_id = window.qpane.createBlankMask(window.qpane.currentImage.size())
        assert mask_id is not None
        assert window.qpane.setActiveMaskID(mask_id)
        window.editor_controls.apply_layer_policy()
        layer = window.qpane.mask_service.assets.get_layer(mask_id)
        assert layer is not None

        def paint_square(pixels: np.ndarray, _image: QImage) -> None:
            """Create content under the tested selection."""
            pixels[60:100, 60:100] = 255

        layer.surface.mutate(paint_square)
        window.qpane.invalidateActiveMaskCache()
        selection = QImage(40, 40, QImage.Format_Grayscale8)
        selection.fill(255)
        assert window.qpane.setPixelSelection(selection, QRect(60, 60, 40, 40))
        window.resize(700, 560)
        window.show()
        window.activateWindow()
        qapp.processEvents()
        assert not window._floating_pixels_toolbar.isVisible()
        coordinates = window.qpane.activeMaskLayerCoordinates()
        start = coordinates.source_to_panel(QPoint(80, 80))
        finish = coordinates.source_to_panel(QPoint(125, 105))
        assert start is not None
        assert finish is not None
        window._set_control_mode(QPane.CONTROL_MODE_MOVE)

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
        assert window._floating_pixels_toolbar.isVisible()
        assert window.editor_controls.anchor_floating_action.isEnabled()
        assert window.editor_controls.promote_floating_action.isEnabled()
        floating_before_space = window.qpane.floatingPixelEditState()
        monkeypatch.setattr(window, "_qpane_under_cursor", lambda _pane: True)
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
        assert window._handle_spacebar_event(window._tools_toolbar, space_press)
        assert window.qpane.getControlMode() == QPane.CONTROL_MODE_PANZOOM
        assert window.qpane.floatingPixelEditState() == floating_before_space
        assert window._handle_spacebar_event(window._tools_toolbar, space_release)
        assert window.qpane.getControlMode() == QPane.CONTROL_MODE_MOVE
        assert window.qpane.floatingPixelEditState() == floating_before_space
        window.editor_controls.cancel_floating_action.trigger()
        qapp.processEvents()
        assert window.qpane.floatingPixelEditState() is None
        assert not window._floating_pixels_toolbar.isVisible()
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()
