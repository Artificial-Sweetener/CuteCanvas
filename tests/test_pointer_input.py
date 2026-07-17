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

"""Tests for normalized Qt direct-input events and widget opt-in."""

from __future__ import annotations

import uuid

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import (
    QImage,
    QInputDevice,
    QMouseEvent,
    QPointingDevice,
    QTabletEvent,
)
from PySide6.QtTest import QTest

from qpane import QPane
from qpane.tools.input import (
    PointerDeviceKind,
    PointerInputController,
    PointerPhase,
)


@pytest.fixture(scope="module")
def pen_device(qapp) -> QPointingDevice:
    return QPointingDevice(
        "Synthetic pen",
        101,
        QInputDevice.DeviceType.Stylus,
        QPointingDevice.PointerType.Pen,
        QInputDevice.Capability.Position
        | QInputDevice.Capability.Pressure
        | QInputDevice.Capability.Hover,
        1,
        1,
    )


def _tablet_event(
    device: QPointingDevice,
    event_type: QEvent.Type,
    pressure: float,
    buttons: Qt.MouseButton,
    position: QPointF = QPointF(10.25, 20.75),
) -> QTabletEvent:
    return QTabletEvent(
        event_type,
        device,
        QPointF(position),
        QPointF(position) + QPointF(100.0, 200.0),
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


def test_tablet_sample_preserves_subpixel_position_and_pressure(
    pen_device: QPointingDevice,
) -> None:
    event = _tablet_event(
        pen_device,
        QEvent.Type.TabletPress,
        0.625,
        Qt.MouseButton.LeftButton,
    )

    sample = PointerInputController.tablet_sample(event)

    assert sample.device is PointerDeviceKind.PEN
    assert sample.phase is PointerPhase.BEGIN
    assert sample.position == QPointF(10.25, 20.75)
    assert sample.global_position == QPointF(110.25, 220.75)
    assert sample.pressure == pytest.approx(0.625)


def test_tablet_sample_classifies_zero_pressure_motion_as_hover(
    pen_device: QPointingDevice,
) -> None:
    event = _tablet_event(
        pen_device,
        QEvent.Type.TabletMove,
        0.0,
        Qt.MouseButton.NoButton,
    )

    sample = PointerInputController.tablet_sample(event)

    assert sample.phase is PointerPhase.HOVER


def test_tablet_sample_treats_generic_stylus_pointer_as_pen(qapp) -> None:
    device = QPointingDevice(
        "Generic stylus",
        103,
        QInputDevice.DeviceType.Stylus,
        QPointingDevice.PointerType.Generic,
        QInputDevice.Capability.Position,
        0,
        1,
    )

    sample = PointerInputController.tablet_sample(
        _tablet_event(
            device,
            QEvent.Type.TabletMove,
            0.0,
            Qt.MouseButton.NoButton,
        )
    )

    assert sample.device is PointerDeviceKind.PEN


def test_qpane_opts_into_touch_and_tablet_tracking(qpane_core) -> None:
    assert qpane_core.testAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)
    assert qpane_core.hasTabletTracking()


def test_qtest_touchscreen_drag_reaches_qpane_navigation(qpane_core, qapp) -> None:
    qpane_core.applySettings(touch_inertia_enabled=False)
    qpane_core.resize(200, 200)
    qpane_core.show()
    image = QImage(800, 800, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.white)
    image_id = uuid.uuid4()
    qpane_core.setImagesByID(
        qpane_core.imageMapFromLists([image], [None], [image_id]),
        image_id,
    )
    qapp.processEvents()
    viewport = qpane_core.view().viewport
    viewport.apply_direct_manipulation(1.0, QPointF())
    device = QTest.createTouchDevice()

    QTest.touchEvent(qpane_core, device).press(0, QPoint(50, 50), qpane_core).commit()
    QTest.touchEvent(qpane_core, device).move(0, QPoint(80, 70), qpane_core).commit()
    qapp.processEvents()
    QTest.touchEvent(qpane_core, device).release(0, QPoint(80, 70), qpane_core).commit()
    qapp.processEvents()

    assert viewport.pan == QPointF(30.0, 20.0)


def test_qtest_double_tap_invokes_panzoom_toggle(
    qpane_core,
    qapp,
    monkeypatch,
) -> None:
    qpane_core.resize(200, 200)
    qpane_core.show()
    image = QImage(400, 400, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.white)
    image_id = uuid.uuid4()
    qpane_core.setImagesByID(
        qpane_core.imageMapFromLists([image], [None], [image_id]),
        image_id,
    )
    qapp.processEvents()
    taps: list[QPointF] = []
    tool = qpane_core._tools_manager.get_active_tool()

    def handle_double_tap(position: QPointF) -> bool:
        taps.append(QPointF(position))
        return True

    monkeypatch.setattr(tool, "handle_double_tap", handle_double_tap)
    device = QTest.createTouchDevice()
    for _tap in range(2):
        QTest.touchEvent(qpane_core, device).press(
            0, QPoint(75, 85), qpane_core
        ).commit()
        QTest.touchEvent(qpane_core, device).release(
            0, QPoint(75, 85), qpane_core
        ).commit()
        qapp.processEvents()

    assert taps == [QPointF(75.0, 85.0)]


def test_qtest_double_tap_toggles_fit_and_one_to_one(qpane_core, qapp) -> None:
    """Stationary double taps must zoom in from Fit and return to Fit."""
    qpane_core.applySettings(
        smooth_zoom_enabled=False,
        touch_inertia_enabled=False,
    )
    qpane_core.resize(300, 200)
    qpane_core.show()
    image = QImage(1200, 800, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.white)
    image_id = uuid.uuid4()
    qpane_core.setImagesByID(
        qpane_core.imageMapFromLists([image], [None], [image_id]),
        image_id,
    )
    qapp.processEvents()
    viewport = qpane_core.view().viewport
    device = QTest.createTouchDevice()

    def double_tap() -> None:
        """Send two stationary taps through QPane's QWidget event surface."""
        for _tap in range(2):
            QTest.touchEvent(qpane_core, device).press(
                0, QPoint(75, 85), qpane_core
            ).commit()
            QTest.touchEvent(qpane_core, device).release(
                0, QPoint(75, 85), qpane_core
            ).commit()
            qapp.processEvents()

    assert viewport.get_zoom_mode().value == "fit"
    assert viewport.zoom == pytest.approx(0.25)

    double_tap()

    assert viewport.get_zoom_mode().value == "1to1"
    assert viewport.zoom == pytest.approx(1.0)

    double_tap()

    assert viewport.get_zoom_mode().value == "fit"
    assert viewport.zoom == pytest.approx(0.25)


def test_synthetic_tablet_event_reaches_active_brush_without_mouse(
    qpane_core,
    qapp,
    pen_device: QPointingDevice,
    monkeypatch,
) -> None:
    samples = []

    class _PointerTool:
        @staticmethod
        def handle_pointer_sample(sample) -> bool:
            samples.append(sample)
            return True

    monkeypatch.setattr(
        qpane_core._tools_manager,
        "get_control_mode",
        lambda: qpane_core.CONTROL_MODE_DRAW_BRUSH,
    )
    monkeypatch.setattr(
        qpane_core._tools_manager,
        "get_active_tool",
        lambda: _PointerTool(),
    )
    event = _tablet_event(
        pen_device,
        QEvent.Type.TabletPress,
        0.75,
        Qt.MouseButton.LeftButton,
    )

    qapp.sendEvent(qpane_core, event)

    assert event.isAccepted()
    assert len(samples) == 1
    assert samples[0].device is PointerDeviceKind.PEN
    assert samples[0].pressure == pytest.approx(0.75)


def test_qtest_single_finger_tap_paints_exactly_one_mask_dab(qapp) -> None:
    viewer = QPane(features=("mask",))
    try:
        viewer.resize(200, 200)
        viewer.show()
        image = QImage(100, 100, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.white)
        image_id = uuid.uuid4()
        viewer.setImagesByID(
            viewer.imageMapFromLists([image], [None], [image_id]),
            image_id,
        )
        mask_id = viewer.createBlankMask(image.size())
        assert mask_id is not None
        service = viewer.mask_service
        assert service is not None
        viewer.setControlMode(viewer.CONTROL_MODE_DRAW_BRUSH)
        tool = viewer._tools_manager.get_active_tool()
        segments = []
        tool.signals.stroke_applied.connect(segments.append)
        qapp.processEvents()
        device = QTest.createTouchDevice()

        QTest.touchEvent(viewer, device).press(0, QPoint(100, 100), viewer).commit()
        QTest.touchEvent(viewer, device).release(0, QPoint(100, 100), viewer).commit()
        qapp.processEvents()

        assert len(segments) == 1
        assert segments[0].start_diameter == pytest.approx(
            viewer.settings.default_brush_size
        )
    finally:
        viewer.deleteLater()
        qapp.processEvents()


def test_two_fingers_navigate_without_painting_in_brush_mode(qapp) -> None:
    viewer = QPane(features=("mask",))
    try:
        viewer.applySettings(touch_inertia_enabled=False)
        viewer.resize(200, 200)
        viewer.show()
        image = QImage(800, 800, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.white)
        image_id = uuid.uuid4()
        viewer.setImagesByID(
            viewer.imageMapFromLists([image], [None], [image_id]),
            image_id,
        )
        mask_id = viewer.createBlankMask(image.size())
        assert mask_id is not None
        service = viewer.mask_service
        assert service is not None
        viewer.setControlMode(viewer.CONTROL_MODE_DRAW_BRUSH)
        viewport = viewer.view().viewport
        qapp.processEvents()
        viewport.apply_direct_manipulation(1.0, QPointF())
        device = QTest.createTouchDevice()

        QTest.touchEvent(viewer, device).press(0, QPoint(60, 80), viewer).commit()
        QTest.touchEvent(viewer, device).move(0, QPoint(60, 80), viewer).press(
            1, QPoint(140, 80), viewer
        ).commit()
        QTest.touchEvent(viewer, device).move(0, QPoint(80, 90), viewer).move(
            1, QPoint(160, 90), viewer
        ).commit()
        qapp.processEvents()
        QTest.touchEvent(viewer, device).release(0, QPoint(80, 90), viewer).release(
            1, QPoint(160, 90), viewer
        ).commit()
        qapp.processEvents()

        mask_layer = service.manager.get_layer(mask_id)
        assert mask_layer is not None
        assert mask_layer.mask_image.pixelColor(360, 380).red() == 0
        assert viewport.pan.x() > 0
        assert viewport.pan.y() > 0
    finally:
        viewer.deleteLater()
        qapp.processEvents()


def _touch_mask_viewer(qapp) -> QPane:
    """Build a shown brush-mode viewer for direct-input feedback tests."""
    viewer = QPane(features=("mask",))
    viewer.resize(200, 200)
    viewer.show()
    image = QImage(100, 100, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.white)
    image_id = uuid.uuid4()
    viewer.setImagesByID(
        viewer.imageMapFromLists([image], [None], [image_id]),
        image_id,
    )
    assert viewer.createBlankMask(image.size()) is not None
    viewer.setControlMode(viewer.CONTROL_MODE_DRAW_BRUSH)
    qapp.processEvents()
    return viewer


def test_pen_hover_shows_nominal_brush_preview_without_painting(
    qapp,
    pen_device: QPointingDevice,
) -> None:
    viewer = _touch_mask_viewer(qapp)
    try:
        tool = viewer._tools_manager.get_active_tool()
        segments = []
        tool.signals.stroke_applied.connect(segments.append)
        event = _tablet_event(
            pen_device,
            QEvent.Type.TabletMove,
            0.0,
            Qt.MouseButton.NoButton,
            QPointF(100.25, 100.75),
        )

        qapp.sendEvent(viewer, event)

        preview = tool.pointer_preview
        assert event.isAccepted()
        assert preview is not None
        assert preview.position == QPointF(100.25, 100.75)
        assert preview.diameter == pytest.approx(viewer.settings.default_brush_size)
        assert preview.contact is False
        assert segments == []
        assert viewer.cursor().shape() == Qt.CursorShape.BlankCursor
    finally:
        viewer.deleteLater()
        qapp.processEvents()


def test_pen_release_returns_to_hover_preview_when_device_supports_hover(
    qapp,
    pen_device: QPointingDevice,
) -> None:
    viewer = _touch_mask_viewer(qapp)
    try:
        tool = viewer._tools_manager.get_active_tool()
        position = QPointF(100.25, 100.75)

        qapp.sendEvent(
            viewer,
            _tablet_event(
                pen_device,
                QEvent.Type.TabletPress,
                0.5,
                Qt.MouseButton.LeftButton,
                position,
            ),
        )
        qapp.sendEvent(
            viewer,
            _tablet_event(
                pen_device,
                QEvent.Type.TabletRelease,
                0.0,
                Qt.MouseButton.NoButton,
                position,
            ),
        )

        preview = tool.pointer_preview
        assert preview is not None
        assert preview.position == position
        assert preview.diameter == pytest.approx(viewer.settings.default_brush_size)
        assert preview.contact is False
    finally:
        viewer.deleteLater()
        qapp.processEvents()


def test_pen_release_clears_preview_when_device_has_no_hover(qapp) -> None:
    device = QPointingDevice(
        "Contact-only pen",
        102,
        QInputDevice.DeviceType.Stylus,
        QPointingDevice.PointerType.Pen,
        QInputDevice.Capability.Position | QInputDevice.Capability.Pressure,
        1,
        1,
    )
    viewer = _touch_mask_viewer(qapp)
    try:
        tool = viewer._tools_manager.get_active_tool()
        position = QPointF(100.0, 100.0)
        qapp.sendEvent(
            viewer,
            _tablet_event(
                device,
                QEvent.Type.TabletPress,
                0.5,
                Qt.MouseButton.LeftButton,
                position,
            ),
        )
        qapp.sendEvent(
            viewer,
            _tablet_event(
                device,
                QEvent.Type.TabletRelease,
                0.0,
                Qt.MouseButton.NoButton,
                position,
            ),
        )

        assert tool.pointer_preview is None
    finally:
        viewer.deleteLater()
        qapp.processEvents()


def test_pen_proximity_leave_clears_brush_preview(
    qapp,
    pen_device: QPointingDevice,
) -> None:
    viewer = _touch_mask_viewer(qapp)
    try:
        tool = viewer._tools_manager.get_active_tool()
        qapp.sendEvent(
            viewer,
            _tablet_event(
                pen_device,
                QEvent.Type.TabletMove,
                0.0,
                Qt.MouseButton.NoButton,
            ),
        )
        assert tool.pointer_preview is not None

        qapp.sendEvent(
            qapp,
            _tablet_event(
                pen_device,
                QEvent.Type.TabletLeaveProximity,
                0.0,
                Qt.MouseButton.NoButton,
            ),
        )

        assert tool.pointer_preview is None
    finally:
        viewer.deleteLater()
        qapp.processEvents()


def test_tool_change_clears_pen_preview(
    qapp,
    pen_device: QPointingDevice,
) -> None:
    viewer = _touch_mask_viewer(qapp)
    try:
        tool = viewer._tools_manager.get_active_tool()
        qapp.sendEvent(
            viewer,
            _tablet_event(
                pen_device,
                QEvent.Type.TabletMove,
                0.0,
                Qt.MouseButton.NoButton,
            ),
        )
        assert tool.pointer_preview is not None

        viewer.setControlMode(viewer.CONTROL_MODE_PANZOOM)

        assert tool.pointer_preview is None
        assert viewer.cursor().shape() != Qt.CursorShape.BlankCursor
    finally:
        viewer.deleteLater()
        qapp.processEvents()


def test_touch_preview_appears_on_press_and_clears_for_two_finger_navigation(
    qapp,
) -> None:
    viewer = _touch_mask_viewer(qapp)
    try:
        tool = viewer._tools_manager.get_active_tool()
        device = QTest.createTouchDevice()

        QTest.touchEvent(viewer, device).press(0, QPoint(90, 100), viewer).commit()
        qapp.processEvents()
        assert tool.pointer_preview is not None
        assert tool.pointer_preview.contact is True

        QTest.touchEvent(viewer, device).stationary(0).press(
            1, QPoint(130, 100), viewer
        ).commit()
        qapp.processEvents()
        assert tool.pointer_preview is None

        QTest.touchEvent(viewer, device).release(0, QPoint(90, 100), viewer).release(
            1, QPoint(130, 100), viewer
        ).commit()
        qapp.processEvents()
    finally:
        viewer.deleteLater()
        qapp.processEvents()


def test_unrelated_pen_proximity_leave_does_not_clear_touch_preview(
    qapp,
    pen_device: QPointingDevice,
) -> None:
    viewer = _touch_mask_viewer(qapp)
    try:
        tool = viewer._tools_manager.get_active_tool()
        touch_device = QTest.createTouchDevice()
        QTest.touchEvent(viewer, touch_device).press(
            0, QPoint(100, 100), viewer
        ).commit()
        qapp.processEvents()
        assert tool.pointer_preview is not None

        qapp.sendEvent(
            qapp,
            _tablet_event(
                pen_device,
                QEvent.Type.TabletLeaveProximity,
                0.0,
                Qt.MouseButton.NoButton,
            ),
        )

        assert tool.pointer_preview is not None
        QTest.touchEvent(viewer, touch_device).release(
            0, QPoint(100, 100), viewer
        ).commit()
        qapp.processEvents()
    finally:
        viewer.deleteLater()
        qapp.processEvents()


def test_palm_rejected_touch_keeps_pen_hover_preview_without_painting(
    qapp,
    pen_device: QPointingDevice,
) -> None:
    viewer = _touch_mask_viewer(qapp)
    try:
        tool = viewer._tools_manager.get_active_tool()
        segments = []
        tool.signals.stroke_applied.connect(segments.append)
        qapp.sendEvent(
            viewer,
            _tablet_event(
                pen_device,
                QEvent.Type.TabletMove,
                0.0,
                Qt.MouseButton.NoButton,
                QPointF(80.0, 80.0),
            ),
        )
        touch_device = QTest.createTouchDevice()

        QTest.touchEvent(viewer, touch_device).press(
            0, QPoint(120, 120), viewer
        ).commit()
        qapp.processEvents()

        assert tool.pointer_preview is not None
        assert tool.pointer_preview.device is PointerDeviceKind.PEN
        assert tool.pointer_preview.position == QPointF(80.0, 80.0)
        assert segments == []
        QTest.touchEvent(viewer, touch_device).release(
            0, QPoint(120, 120), viewer
        ).commit()
        qapp.processEvents()
    finally:
        viewer.deleteLater()
        qapp.processEvents()


def test_genuine_mouse_activity_restores_brush_cursor_after_touch(qapp) -> None:
    viewer = _touch_mask_viewer(qapp)
    try:
        device = QTest.createTouchDevice()
        QTest.touchEvent(viewer, device).press(0, QPoint(100, 100), viewer).commit()
        QTest.touchEvent(viewer, device).release(0, QPoint(100, 100), viewer).commit()
        qapp.processEvents()
        assert viewer.cursor().shape() == Qt.CursorShape.BlankCursor

        mouse_move = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(110.0, 100.0),
            QPointF(110.0, 100.0),
            QPointF(110.0, 100.0),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.MouseEventSource.MouseEventNotSynthesized,
        )
        qapp.sendEvent(viewer, mouse_move)

        assert viewer.cursor().shape() != Qt.CursorShape.BlankCursor
    finally:
        viewer.deleteLater()
        qapp.processEvents()


def test_synthesized_mouse_press_after_touch_does_not_duplicate_stroke(qapp) -> None:
    viewer = _touch_mask_viewer(qapp)
    try:
        tool = viewer._tools_manager.get_active_tool()
        segments = []
        tool.signals.stroke_applied.connect(segments.append)
        device = QTest.createTouchDevice()
        QTest.touchEvent(viewer, device).press(0, QPoint(100, 100), viewer).commit()
        QTest.touchEvent(viewer, device).release(0, QPoint(100, 100), viewer).commit()
        qapp.processEvents()
        touch_segment_count = len(segments)

        for event_type, button, buttons in (
            (
                QEvent.Type.MouseButtonPress,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
            ),
            (
                QEvent.Type.MouseButtonRelease,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton,
            ),
        ):
            event = QMouseEvent(
                event_type,
                QPointF(100.0, 100.0),
                QPointF(100.0, 100.0),
                QPointF(100.0, 100.0),
                button,
                buttons,
                Qt.KeyboardModifier.NoModifier,
                Qt.MouseEventSource.MouseEventSynthesizedByQt,
            )
            qapp.sendEvent(viewer, event)

        assert touch_segment_count == 1
        assert len(segments) == touch_segment_count
    finally:
        viewer.deleteLater()
        qapp.processEvents()
