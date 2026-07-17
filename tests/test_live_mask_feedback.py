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

from collections.abc import Callable
from dataclasses import dataclass
import time
import uuid

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QImage,
    QInputDevice,
    QMouseEvent,
    QPointingDevice,
    QTabletEvent,
)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from qpane import QPane


@dataclass(frozen=True, slots=True)
class VisibleFeedbackMeasurement:
    """Record presentation latency and the observed mounted-widget pixel."""

    latency_ms: float | None
    color: QColor


class MountedMaskFeedbackProbe:
    """Mount a real offscreen QPane and sample its composited widget pixels."""

    def __init__(
        self,
        qapp: QApplication,
        *,
        image_size: QSize = QSize(400, 400),
    ) -> None:
        """Create a shown brush-mode pane with one publicly created mask."""
        self._qapp = qapp
        self.viewer = QPane(features=("mask",))
        self.viewer.resize(400, 400)
        self.viewer.show()
        image = QImage(image_size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.white)
        image_id = uuid.uuid4()
        self.viewer.setImagesByID(
            self.viewer.imageMapFromLists([image], [None], [image_id]),
            image_id,
        )
        assert self.viewer.createBlankMask(image.size()) is not None
        self.viewer.setControlMode(self.viewer.CONTROL_MODE_DRAW_BRUSH)
        self.viewer.setBrushSize(30)
        self._qapp.processEvents()
        QTest.qWait(5)

    def close(self) -> None:
        """Dispose the mounted pane and drain its queued Qt work."""
        self.viewer.close()
        self.viewer.deleteLater()
        self._qapp.processEvents()

    def wait_for_visible_paint(
        self,
        point: QPoint,
        *,
        timeout_ms: int = 150,
    ) -> VisibleFeedbackMeasurement:
        """Measure time until the mask tint reaches ``point`` on the widget."""
        return self._wait_for_color(point, self._is_mask_tint, timeout_ms=timeout_ms)

    def wait_for_white(
        self,
        point: QPoint,
        *,
        timeout_ms: int = 150,
    ) -> VisibleFeedbackMeasurement:
        """Measure time until provisional paint is absent at ``point``."""
        return self._wait_for_color(point, self._is_white, timeout_ms=timeout_ms)

    def _wait_for_color(
        self,
        point: QPoint,
        predicate: Callable[[QColor], bool],
        *,
        timeout_ms: int,
    ) -> VisibleFeedbackMeasurement:
        """Poll real widget composition until ``predicate`` accepts its pixel."""
        started_at = time.perf_counter()
        deadline = started_at + timeout_ms / 1000.0
        color = QColor()
        while time.perf_counter() < deadline:
            self._qapp.processEvents()
            color = self.viewer.grab().toImage().pixelColor(point)
            if predicate(color):
                return VisibleFeedbackMeasurement(
                    latency_ms=(time.perf_counter() - started_at) * 1000.0,
                    color=color,
                )
            QTest.qWait(1)
        return VisibleFeedbackMeasurement(latency_ms=None, color=color)

    @staticmethod
    def _is_mask_tint(color: QColor) -> bool:
        """Return whether ``color`` contains the default red mask overlay."""
        return color.red() - color.green() >= 40 and color.green() < 230

    @staticmethod
    def _is_white(color: QColor) -> bool:
        """Return whether ``color`` is the unmasked white source image."""
        return color.red() >= 250 and color.green() >= 250 and color.blue() >= 250


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
