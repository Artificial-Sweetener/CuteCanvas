#    QPane - High-performance PySide6 image viewer
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

"""Mounted-widget probes for visible mask feedback before stroke release."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QInputDevice, QMouseEvent, QPointingDevice, QTabletEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from qpane import QPane
from tests.harness import MountedQPaneHarness
from tests.harness.abuse_model import HarnessPoint, PointerKind, StrokeAction
from tests.harness.input_driver import QtStrokeDriver


class MountedMaskFeedbackProbe(MountedQPaneHarness):
    """Mount a real offscreen QPane and sample its composited widget pixels."""

    def __init__(
        self,
        qapp: QApplication,
        *,
        image_size: QSize | None = None,
    ) -> None:
        """Create a shown brush-mode pane with one publicly created mask."""
        super().__init__(qapp, image_size=image_size)
        self._qapp = qapp

    def wait_for_visible_paint(self, point: QPoint, *, timeout_ms: int = 150):
        """Measure time until the mask tint reaches ``point`` on the widget."""
        return self.wait_for_mask_tint(point, timeout_ms=timeout_ms)

    def wait_for_white(self, point: QPoint, *, timeout_ms: int = 150):
        """Measure time until provisional paint is absent at ``point``."""
        return self.wait_for_background(point, timeout_ms=timeout_ms)

    _is_mask_tint = staticmethod(MountedQPaneHarness.is_mask_tint)


@pytest.mark.parametrize("image_size", [QSize(400, 400), QSize(1600, 1600)])
def test_mouse_contact_presents_mask_before_release(
    qapp: QApplication,
    image_size: QSize,
) -> None:
    """Mouse contact must tint mounted pixels before its button is released."""
    probe = MountedMaskFeedbackProbe(qapp, image_size=image_size)
    point = QPoint(200, 200)
    try:
        QTest.mousePress(
            probe.viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            point,
        )

        measurement = probe.wait_for_visible_paint(point)

        assert measurement.latency_ms is not None, measurement.color.getRgb()
        QTest.mouseRelease(
            probe.viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            point,
        )
    finally:
        probe.close()


@pytest.mark.parametrize("image_size", [QSize(400, 400), QSize(1600, 1600)])
def test_touch_contact_presents_mask_before_release(
    qapp: QApplication,
    image_size: QSize,
) -> None:
    """A stationary painting finger must tint mounted pixels while held down."""
    probe = MountedMaskFeedbackProbe(qapp, image_size=image_size)
    point = QPoint(200, 200)
    device = QTest.createTouchDevice()
    try:
        QTest.touchEvent(probe.viewer, device).press(0, point, probe.viewer).commit()

        measurement = probe.wait_for_visible_paint(point)

        assert measurement.latency_ms is not None, measurement.color.getRgb()
        QTest.touchEvent(probe.viewer, device).release(0, point, probe.viewer).commit()
    finally:
        probe.close()


def test_pen_contact_presents_mask_before_release(qapp: QApplication) -> None:
    """Synthetic stylus pressure must tint mounted pixels before pen-up."""
    probe = MountedMaskFeedbackProbe(qapp)
    point = QPointF(200.0, 200.0)
    device = QPointingDevice(
        "Synthetic pen",
        501,
        QInputDevice.DeviceType.Stylus,
        QPointingDevice.PointerType.Pen,
        QInputDevice.Capability.Position
        | QInputDevice.Capability.Pressure
        | QInputDevice.Capability.Hover,
        1,
        1,
    )
    try:
        press = _tablet_event(
            device,
            QEvent.Type.TabletPress,
            point,
            pressure=0.75,
            buttons=Qt.MouseButton.LeftButton,
        )
        qapp.sendEvent(probe.viewer, press)

        measurement = probe.wait_for_visible_paint(point.toPoint())

        assert press.isAccepted()
        assert measurement.latency_ms is not None, measurement.color.getRgb()
        qapp.sendEvent(
            probe.viewer,
            _tablet_event(
                device,
                QEvent.Type.TabletRelease,
                point,
                pressure=0.0,
                buttons=Qt.MouseButton.NoButton,
            ),
        )
    finally:
        probe.close()


def test_rapid_second_mouse_drag_presents_new_pixels_before_release(
    qapp: QApplication,
) -> None:
    """A rapid nearby second press must not suppress its subsequent drag."""
    probe = MountedMaskFeedbackProbe(qapp)
    start = QPoint(140, 200)
    destination = QPoint(260, 200)
    try:
        QTest.mouseClick(
            probe.viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            start,
        )
        QTest.mousePress(
            probe.viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            start,
        )
        QTest.mouseMove(probe.viewer, destination, delay=1)

        measurement = probe.wait_for_visible_paint(destination)

        assert measurement.latency_ms is not None, measurement.color.getRgb()
        QTest.mouseRelease(
            probe.viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            destination,
        )
    finally:
        probe.close()


def test_held_mouse_drag_presents_filled_continuous_stroke_before_release(
    qapp: QApplication,
) -> None:
    """A moving preview must remain filled across its accumulated interior."""
    probe = MountedMaskFeedbackProbe(qapp)
    probe.viewer.setBrushSize(40)
    start = QPoint(100, 200)
    end = QPoint(300, 200)
    try:
        QTest.mousePress(
            probe.viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            start,
        )
        for x_position in range(120, end.x() + 1, 20):
            QTest.mouseMove(probe.viewer, QPoint(x_position, 200), delay=1)
            qapp.processEvents()

        missing_pixels = [
            (x_position, y_position)
            for x_position in range(110, 281, 10)
            for y_position in (190, 200, 210)
            if not probe._is_mask_tint(
                probe.viewer.grab().toImage().pixelColor(x_position, y_position)
            )
        ]

        assert missing_pixels == []
        QTest.mouseRelease(
            probe.viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            end,
        )
    finally:
        probe.close()


@pytest.mark.parametrize("device", tuple(PointerKind))
def test_decimated_drag_preview_presents_each_move_without_forced_grab(
    qapp: QApplication,
    device: PointerKind,
) -> None:
    """Low-zoom preview frames must show every held-contact move naturally."""
    probe = MountedQPaneHarness(
        qapp,
        image_size=QSize(4096, 4096),
        widget_size=QSize(320, 500),
        brush_size=30,
    )
    action = StrokeAction(
        device=device,
        points=tuple(
            HarnessPoint(x_position, 250) for x_position in range(48, 273, 32)
        ),
        brush_size=30,
        step_delay_ms=1,
    )
    driver = QtStrokeDriver(probe)
    pressed = False
    try:
        assert probe.viewer.currentZoom() == pytest.approx(0.078125)
        with probe.observe_presented_frames() as frame_probe:
            for point_index, harness_point in enumerate(action.points):
                point = harness_point.to_qpoint()
                frame_count = len(frame_probe.frames)
                if point_index == 0:
                    driver.begin(action)
                    pressed = True
                else:
                    driver.move(action, point_index)
                QTest.qWait(20)
                qapp.processEvents()

                presented = frame_probe.frames[frame_count:]
                assert presented, f"move {point_index} did not present a frame"
                frame = presented[-1]
                assert any(
                    probe.is_mask_tint(frame.color_at(point + QPoint(dx, dy)))
                    for dy in range(-4, 5)
                    for dx in range(-4, 5)
                ), f"move {point_index} presented no mask feedback"
    finally:
        if pressed:
            driver.end(action)
        probe.close()


def test_mouse_brush_cursor_stays_high_contrast_across_input_transitions(
    qapp: QApplication,
) -> None:
    """The mouse brush cursor must remain a visible dual-tone size preview."""
    probe = MountedMaskFeedbackProbe(qapp)
    point = QPoint(180, 200)
    try:
        _assert_high_contrast_brush_cursor(probe.viewer)
        QTest.mouseMove(probe.viewer, point)
        _assert_high_contrast_brush_cursor(probe.viewer)
        QTest.mousePress(
            probe.viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            point,
        )
        QTest.mouseMove(probe.viewer, point + QPoint(30, 0), delay=1)
        _assert_high_contrast_brush_cursor(probe.viewer)
        QTest.mouseRelease(
            probe.viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            point + QPoint(30, 0),
        )
        touch_device = QTest.createTouchDevice()
        QTest.touchEvent(probe.viewer, touch_device).press(
            0, point, probe.viewer
        ).commit()
        QTest.touchEvent(probe.viewer, touch_device).release(
            0, point, probe.viewer
        ).commit()
        mouse_move = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(point),
            QPointF(point),
            QPointF(point),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.MouseEventSource.MouseEventNotSynthesized,
        )
        qapp.sendEvent(probe.viewer, mouse_move)

        _assert_high_contrast_brush_cursor(probe.viewer)
    finally:
        probe.close()


def test_second_touch_rolls_back_provisional_dab_before_navigation(
    qapp: QApplication,
) -> None:
    """Two-finger takeover must remove its provisional dab and navigate cleanly."""
    probe = MountedMaskFeedbackProbe(qapp, image_size=QSize(800, 800))
    probe.viewer.applySettings(touch_inertia_enabled=False)
    probe.viewer.view().viewport.apply_direct_manipulation(1.0, QPointF())
    first = QPoint(160, 200)
    second = QPoint(240, 200)
    device = QTest.createTouchDevice()
    try:
        QTest.touchEvent(probe.viewer, device).press(0, first, probe.viewer).commit()
        assert probe.wait_for_visible_paint(first).latency_ms is not None

        QTest.touchEvent(probe.viewer, device).move(0, first, probe.viewer).press(
            1, second, probe.viewer
        ).commit()

        rollback = probe.wait_for_white(first)
        assert rollback.latency_ms is not None, rollback.color.getRgb()
        QTest.touchEvent(probe.viewer, device).move(
            0, first + QPoint(20, 10), probe.viewer
        ).move(1, second + QPoint(20, 10), probe.viewer).commit()
        probe._qapp.processEvents()
        assert probe.viewer.getPan() != QPointF()
        QTest.touchEvent(probe.viewer, device).release(
            0, first + QPoint(20, 10), probe.viewer
        ).release(1, second + QPoint(20, 10), probe.viewer).commit()
    finally:
        probe.close()


def _tablet_event(
    device: QPointingDevice,
    event_type: QEvent.Type,
    position: QPointF,
    *,
    pressure: float,
    buttons: Qt.MouseButton,
) -> QTabletEvent:
    """Build one pressure-bearing tablet event for the mounted stylus probe."""
    return QTabletEvent(
        event_type,
        device,
        position,
        position,
        pressure,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        Qt.KeyboardModifier.NoModifier,
        Qt.MouseButton.LeftButton if buttons else Qt.MouseButton.NoButton,
        buttons,
    )


def _assert_high_contrast_brush_cursor(viewer: QPane) -> None:
    """Assert that ``viewer`` exposes a non-empty cursor with dark and light pixels."""
    cursor_pixmap = viewer.cursor().pixmap()
    assert not cursor_pixmap.isNull()
    cursor_image = cursor_pixmap.toImage()
    opaque_colors = [
        cursor_image.pixelColor(x_position, y_position)
        for y_position in range(cursor_image.height())
        for x_position in range(cursor_image.width())
        if cursor_image.pixelColor(x_position, y_position).alpha() >= 128
    ]
    assert opaque_colors
    assert any(color.value() <= 32 for color in opaque_colors)
    assert any(color.value() >= 223 for color in opaque_colors)
