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

"""Tests for normalized Qt direct-input events and widget opt-in."""

from __future__ import annotations

import uuid

import pytest
from cutecanvas import CuteCanvas, LayerPolicy
from cutecanvas.tools.input import PointerInputController
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import (
    QEnterEvent,
    QEventPoint,
    QImage,
    QInputDevice,
    QMouseEvent,
    QPointingDevice,
    QTabletEvent,
    QTouchEvent,
)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
from qpane import (
    PointerDeviceKind,
    PointerPhase,
    ToolInputProfile,
)

from tests.harness import PointerTransitionProbe


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
    position: QPointF | None = None,
) -> QTabletEvent:
    position = QPointF(10.25, 20.75) if position is None else QPointF(position)
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
        """Send two stationary taps through CuteCanvas's QWidget event surface."""
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
        input_profile = ToolInputProfile(tablet=True)

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
    viewer = CuteCanvas(features=("mask",))
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
    viewer = CuteCanvas(features=("mask",))
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

        mask_layer = service.assets.get_layer(mask_id)
        assert mask_layer is not None
        assert mask_layer.mask_image.pixelColor(360, 380).red() == 0
        assert viewport.pan.x() > 0
        assert viewport.pan.y() > 0
    finally:
        viewer.deleteLater()
        qapp.processEvents()


def test_single_finger_move_tool_translates_policy_enabled_layer(qapp) -> None:
    """Move touch input should not depend on the host's brush enablement setting."""
    viewer = CuteCanvas(features=())
    try:
        viewer.applySettings(touch_paint_enabled=False)
        viewer.resize(200, 200)
        viewer.show()
        image = QImage(100, 100, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.white)
        image_id = uuid.uuid4()
        viewer.setImagesByID(
            viewer.imageMapFromLists([image], [None], [image_id]),
            image_id,
        )
        scene = viewer.currentScene()
        assert scene is not None
        layer = scene.layers[0]
        assert viewer.setLayerInteractionPolicy(
            scene.scene_id,
            layer.layer_id,
            LayerPolicy(selectable=True, movable=True),
        )
        viewer.setControlMode(viewer.CONTROL_MODE_MOVE)
        qapp.processEvents()
        device = QTest.createTouchDevice()

        QTest.touchEvent(viewer, device).press(0, QPoint(100, 100), viewer).commit()
        QTest.touchEvent(viewer, device).move(0, QPoint(120, 110), viewer).commit()
        QTest.touchEvent(viewer, device).release(0, QPoint(120, 110), viewer).commit()
        qapp.processEvents()

        moved = viewer.currentScene()
        assert moved is not None
        assert moved.layers[0].placement.x() > layer.placement.x()
        assert moved.layers[0].placement.y() > layer.placement.y()
        assert viewer.sceneEditUndoAvailable()
    finally:
        viewer.deleteLater()
        qapp.processEvents()


def _touch_mask_viewer(qapp) -> CuteCanvas:
    """Build a shown brush-mode viewer for direct-input feedback tests."""
    viewer = CuteCanvas(features=("mask",))
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


def test_palm_rejected_touch_preserves_pen_modality_until_proximity_leave(
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


@pytest.mark.parametrize(
    "source",
    (
        Qt.MouseEventSource.MouseEventNotSynthesized,
        Qt.MouseEventSource.MouseEventSynthesizedByQt,
        Qt.MouseEventSource.MouseEventSynthesizedBySystem,
        Qt.MouseEventSource.MouseEventSynthesizedByApplication,
    ),
)
def test_touch_release_restores_cursor_before_mouse_motion_adopts_modality(
    qapp,
    source: Qt.MouseEventSource,
) -> None:
    viewer = _touch_mask_viewer(qapp)
    try:
        device = QTest.createTouchDevice()
        QTest.touchEvent(viewer, device).press(0, QPoint(100, 100), viewer).commit()
        QTest.touchEvent(viewer, device).release(0, QPoint(100, 100), viewer).commit()
        qapp.processEvents()
        assert viewer.cursor().shape() != Qt.CursorShape.BlankCursor
        assert (
            viewer.interaction._pointer_input.active_device is PointerDeviceKind.TOUCH
        )

        mouse_move = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(100.0, 100.0),
            QPointF(100.0, 100.0),
            QPointF(100.0, 100.0),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            source,
        )
        qapp.sendEvent(viewer, mouse_move)

        assert viewer.cursor().shape() != Qt.CursorShape.BlankCursor
        assert (
            viewer.interaction._pointer_input.active_device is PointerDeviceKind.MOUSE
        )
        cursor_image = viewer.cursor().pixmap().toImage()
        assert not cursor_image.isNull()
        opaque_values = [
            cursor_image.pixelColor(x_position, y_position).value()
            for y_position in range(cursor_image.height())
            for x_position in range(cursor_image.width())
            if cursor_image.pixelColor(x_position, y_position).alpha() >= 128
        ]
        assert opaque_values
        assert min(opaque_values) <= 32
        assert max(opaque_values) >= 223
        assert (
            viewer.interaction._pointer_input.active_device is PointerDeviceKind.MOUSE
        )
    finally:
        viewer.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize(
    "source",
    (
        Qt.MouseEventSource.MouseEventSynthesizedByQt,
        Qt.MouseEventSource.MouseEventSynthesizedBySystem,
        Qt.MouseEventSource.MouseEventSynthesizedByApplication,
    ),
)
@pytest.mark.parametrize("metadata", ("touchscreen", "unknown"))
def test_hover_motion_after_touch_restores_cursor_with_stale_device_metadata(
    qapp,
    source: Qt.MouseEventSource,
    metadata: str,
) -> None:
    """A post-contact no-button move must restore hover despite stale metadata."""
    viewer = _touch_mask_viewer(qapp)
    try:
        touch_device = QTest.createTouchDevice()
        event_device = (
            touch_device
            if metadata == "touchscreen"
            else QPointingDevice(
                "Unknown synthesized pointer",
                702,
                QInputDevice.DeviceType.Unknown,
                QPointingDevice.PointerType.Generic,
                QInputDevice.Capability.Position,
                1,
                1,
            )
        )
        position = QPointF(100.0, 100.0)
        QTest.touchEvent(viewer, touch_device).press(
            0, position.toPoint(), viewer
        ).commit()
        QTest.touchEvent(viewer, touch_device).release(
            0, position.toPoint(), viewer
        ).commit()
        qapp.processEvents()
        promoted_move = QMouseEvent(
            QEvent.Type.MouseMove,
            position,
            position,
            position,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            source,
            event_device,
        )
        qapp.sendEvent(viewer, promoted_move)

        cursor = viewer.cursor()
        cursor_image = cursor.pixmap().toImage()
        assert cursor.shape() != Qt.CursorShape.BlankCursor
        assert not cursor_image.isNull()
        assert cursor.hotSpot() == QPoint(
            cursor_image.width() // 2,
            cursor_image.height() // 2,
        )
        opaque_values = [
            cursor_image.pixelColor(x_position, y_position).value()
            for y_position in range(cursor_image.height())
            for x_position in range(cursor_image.width())
            if cursor_image.pixelColor(x_position, y_position).alpha() >= 128
        ]
        assert opaque_values
        assert min(opaque_values) <= 32
        assert max(opaque_values) >= 223
        assert (
            viewer.interaction._pointer_input.active_device is PointerDeviceKind.MOUSE
        )
    finally:
        viewer.deleteLater()
        qapp.processEvents()


def test_transition_probe_records_touch_release_before_mouse_recovery(qapp) -> None:
    """The probe must expose contact-only suppression and later mouse ownership."""
    viewer = _touch_mask_viewer(qapp)
    probe = PointerTransitionProbe(viewer)
    touch_device = QTest.createTouchDevice()
    position = QPointF(100.0, 100.0)
    try:
        touch_begin = probe.deliver(
            QTouchEvent(
                QEvent.Type.TouchBegin,
                touch_device,
                Qt.KeyboardModifier.NoModifier,
                (
                    QEventPoint(
                        0,
                        QEventPoint.State.Pressed,
                        position,
                        position,
                    ),
                ),
            )
        )
        assert touch_begin.event_type == "TouchBegin"
        assert touch_begin.device_type == "TouchScreen"
        assert touch_begin.accepted_after is True
        assert touch_begin.active_device == "touch"
        assert touch_begin.touch_claimed is True
        assert touch_begin.cursor_suppressed is True
        assert touch_begin.cursor_shape == "BlankCursor"
        assert touch_begin.effective_cursor_shape == "BlankCursor"

        touch_end = probe.deliver(
            QTouchEvent(
                QEvent.Type.TouchEnd,
                touch_device,
                Qt.KeyboardModifier.NoModifier,
                (
                    QEventPoint(
                        0,
                        QEventPoint.State.Released,
                        position,
                        position,
                    ),
                ),
            )
        )
        assert touch_end.event_type == "TouchEnd"
        assert touch_end.accepted_after is True
        assert touch_end.active_device == "touch"
        assert touch_end.touch_claimed is False
        assert touch_end.cursor_suppressed is False
        assert touch_end.cursor_shape != "BlankCursor"
        assert touch_end.effective_cursor_shape != "BlankCursor"
        assert touch_end.cursor_size[0] > 0
        assert touch_end.cursor_size[1] > 0

        mouse_move = QMouseEvent(
            QEvent.Type.MouseMove,
            position,
            position,
            position,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.MouseEventSource.MouseEventSynthesizedBySystem,
            touch_device,
        )
        mouse_observation = probe.deliver(mouse_move)

        assert mouse_observation.event_type == "MouseMove"
        assert mouse_observation.source == "MouseEventSynthesizedBySystem"
        assert mouse_observation.device_type == "TouchScreen"
        assert mouse_observation.active_device == "mouse"
        assert mouse_observation.touch_claimed is False
        assert mouse_observation.cursor_suppressed is False
        assert mouse_observation.cursor_shape != "BlankCursor"
        assert mouse_observation.effective_cursor_shape != "BlankCursor"
        assert mouse_observation.cursor_size[0] > 0
        assert mouse_observation.cursor_size[1] > 0
        assert mouse_observation.cursor_hotspot == (
            mouse_observation.cursor_size[0] // 2,
            mouse_observation.cursor_size[1] // 2,
        )
    finally:
        probe.close()
        viewer.deleteLater()
        qapp.processEvents()


def test_repeated_touch_contacts_suppress_cursor_only_while_claimed(qapp) -> None:
    """Each touch must hide during contact and restore without a device change."""
    viewer = _touch_mask_viewer(qapp)
    touch_device = QTest.createTouchDevice()
    try:
        for point in (QPoint(80, 90), QPoint(140, 150), QPoint(200, 210)):
            QTest.touchEvent(viewer, touch_device).press(0, point, viewer).commit()
            qapp.processEvents()

            assert viewer.cursor().shape() == Qt.CursorShape.BlankCursor
            assert viewer.interaction._pointer_input.touch_sequence_claimed is True
            assert (
                viewer.interaction._pointer_input.active_device
                is PointerDeviceKind.TOUCH
            )

            QTest.touchEvent(viewer, touch_device).release(0, point, viewer).commit()
            qapp.processEvents()

            cursor = viewer.cursor()
            assert cursor.shape() != Qt.CursorShape.BlankCursor
            assert not cursor.pixmap().isNull()
            assert viewer.interaction._pointer_input.touch_sequence_claimed is False
            assert (
                viewer.interaction._pointer_input.active_device
                is PointerDeviceKind.TOUCH
            )
    finally:
        viewer.deleteLater()
        qapp.processEvents()


def test_transition_probe_records_ignored_touch_on_blank_pane(qapp) -> None:
    """Unsupported touch delivery must remain unclaimed and preserve cursor policy."""
    viewer = _touch_mask_viewer(qapp)
    probe = PointerTransitionProbe(viewer)
    touch_device = QTest.createTouchDevice()
    position = QPointF(100.0, 100.0)
    try:
        viewer.clearImages()
        qapp.processEvents()
        observation = probe.deliver(
            QTouchEvent(
                QEvent.Type.TouchBegin,
                touch_device,
                Qt.KeyboardModifier.NoModifier,
                (
                    QEventPoint(
                        0,
                        QEventPoint.State.Pressed,
                        position,
                        position,
                    ),
                ),
            )
        )

        assert observation.event_type == "TouchBegin"
        assert observation.device_type == "TouchScreen"
        assert observation.accepted_after is False
        assert observation.active_device == "unknown"
        assert observation.touch_claimed is False
        assert observation.cursor_shape != "BlankCursor"
    finally:
        probe.close()
        viewer.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("embedded", (False, True), ids=("top-level", "embedded"))
@pytest.mark.parametrize(
    "lifecycle_events",
    (
        (),
        (QEvent.Type.FocusOut, QEvent.Type.FocusIn),
        (QEvent.Type.GrabMouse, QEvent.Type.UngrabMouse),
        (QEvent.Type.WindowDeactivate, QEvent.Type.WindowActivate),
    ),
    ids=("steady", "focus", "grab", "activation"),
)
def test_touch_mouse_recovery_survives_widget_lifecycle_and_hierarchy(
    qapp,
    embedded: bool,
    lifecycle_events: tuple[QEvent.Type, ...],
) -> None:
    """Widget lifecycle transitions must not strand touch cursor ownership."""
    viewer = _touch_mask_viewer(qapp)
    container = QWidget() if embedded else None
    touch_device = QTest.createTouchDevice()
    position = QPointF(100.0, 100.0)
    try:
        if container is not None:
            viewer.setParent(container)
            container.resize(240, 240)
            viewer.show()
            container.show()
            qapp.processEvents()
        QTest.touchEvent(viewer, touch_device).press(
            0, position.toPoint(), viewer
        ).commit()
        QTest.touchEvent(viewer, touch_device).release(
            0, position.toPoint(), viewer
        ).commit()
        qapp.processEvents()
        assert viewer.cursor().shape() != Qt.CursorShape.BlankCursor
        assert (
            viewer.interaction._pointer_input.active_device is PointerDeviceKind.TOUCH
        )

        for event_type in lifecycle_events:
            qapp.sendEvent(viewer, QEvent(event_type))
        mouse_move = QMouseEvent(
            QEvent.Type.MouseMove,
            position,
            position,
            position,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.MouseEventSource.MouseEventSynthesizedBySystem,
            touch_device,
        )
        qapp.sendEvent(viewer, mouse_move)

        assert viewer.cursor().shape() != Qt.CursorShape.BlankCursor
        assert (
            viewer.interaction._pointer_input.active_device is PointerDeviceKind.MOUSE
        )
    finally:
        viewer.setParent(None)
        viewer.deleteLater()
        if container is not None:
            container.deleteLater()
        qapp.processEvents()


def test_synthesized_hover_during_active_touch_remains_suppressed(qapp) -> None:
    """A mouse-shaped compatibility move cannot steal an active touch sequence."""
    viewer = _touch_mask_viewer(qapp)
    touch_device = QTest.createTouchDevice()
    position = QPointF(100.0, 100.0)
    try:
        QTest.touchEvent(viewer, touch_device).press(
            0, position.toPoint(), viewer
        ).commit()
        qapp.processEvents()
        compatibility_move = QMouseEvent(
            QEvent.Type.MouseMove,
            position,
            position,
            position,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.MouseEventSource.MouseEventSynthesizedBySystem,
            touch_device,
        )

        qapp.sendEvent(viewer, compatibility_move)

        assert viewer.cursor().shape() == Qt.CursorShape.BlankCursor
        assert viewer.interaction._pointer_input.touch_sequence_claimed is True
        assert (
            viewer.interaction._pointer_input.active_device is PointerDeviceKind.TOUCH
        )
    finally:
        QTest.touchEvent(viewer, touch_device).release(
            0, position.toPoint(), viewer
        ).commit()
        viewer.deleteLater()
        qapp.processEvents()


def test_hover_motion_restores_cursor_after_touch_cancel(qapp) -> None:
    """Cancelled touch ownership must not strand the brush on BlankCursor."""
    viewer = _touch_mask_viewer(qapp)
    touch_device = QTest.createTouchDevice()
    position = QPointF(100.0, 100.0)
    try:
        QTest.touchEvent(viewer, touch_device).press(
            0, position.toPoint(), viewer
        ).commit()
        qapp.processEvents()
        cancel_event = QTouchEvent(
            QEvent.Type.TouchCancel,
            touch_device,
            Qt.KeyboardModifier.NoModifier,
            (),
        )
        qapp.sendEvent(viewer, cancel_event)
        assert viewer.cursor().shape() != Qt.CursorShape.BlankCursor
        assert viewer.interaction._pointer_input.touch_sequence_claimed is False
        hover_event = QMouseEvent(
            QEvent.Type.MouseMove,
            position,
            position,
            position,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.MouseEventSource.MouseEventSynthesizedBySystem,
            touch_device,
        )

        qapp.sendEvent(viewer, hover_event)

        assert viewer.cursor().shape() != Qt.CursorShape.BlankCursor
        assert viewer.interaction._pointer_input.touch_sequence_claimed is False
        assert (
            viewer.interaction._pointer_input.active_device is PointerDeviceKind.MOUSE
        )
    finally:
        viewer.deleteLater()
        qapp.processEvents()


def test_mouse_enter_adopts_mouse_after_touch_cursor_is_restored(qapp) -> None:
    """Touch release restores the brush before enter adopts mouse ownership."""
    viewer = _touch_mask_viewer(qapp)
    try:
        touch_device = QTest.createTouchDevice()
        point = QPoint(100, 100)
        QTest.touchEvent(viewer, touch_device).press(0, point, viewer).commit()
        QTest.touchEvent(viewer, touch_device).release(0, point, viewer).commit()
        qapp.processEvents()
        assert viewer.cursor().shape() != Qt.CursorShape.BlankCursor
        assert (
            viewer.interaction._pointer_input.active_device is PointerDeviceKind.TOUCH
        )

        enter_event = QEnterEvent(QPointF(point), QPointF(point), QPointF(point))
        qapp.sendEvent(viewer, enter_event)
        qapp.processEvents()

        assert viewer.cursor().shape() != Qt.CursorShape.BlankCursor
        assert (
            viewer.interaction._pointer_input.active_device is PointerDeviceKind.MOUSE
        )
    finally:
        viewer.deleteLater()
        qapp.processEvents()


def test_stylus_promoted_mouse_motion_does_not_steal_pen_hover(
    qapp,
    pen_device: QPointingDevice,
) -> None:
    """Mouse-shaped tablet synthesis must preserve the active pen preview."""
    viewer = _touch_mask_viewer(qapp)
    try:
        position = QPointF(100.0, 100.0)
        qapp.sendEvent(
            viewer,
            _tablet_event(
                pen_device,
                QEvent.Type.TabletMove,
                0.0,
                Qt.MouseButton.NoButton,
                position,
            ),
        )
        promoted_move = QMouseEvent(
            QEvent.Type.MouseMove,
            position,
            position,
            position,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.MouseEventSource.MouseEventSynthesizedBySystem,
            pen_device,
        )

        qapp.sendEvent(viewer, promoted_move)

        assert viewer.cursor().shape() == Qt.CursorShape.BlankCursor
        assert viewer.interaction._pointer_input.active_device is PointerDeviceKind.PEN
    finally:
        viewer.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize(
    "source",
    (
        Qt.MouseEventSource.MouseEventSynthesizedByQt,
        Qt.MouseEventSource.MouseEventSynthesizedBySystem,
        Qt.MouseEventSource.MouseEventSynthesizedByApplication,
    ),
)
def test_synthesized_mouse_press_after_touch_does_not_duplicate_stroke(
    qapp,
    source: Qt.MouseEventSource,
) -> None:
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
                source,
                device,
            )
            qapp.sendEvent(viewer, event)

        assert touch_segment_count == 1
        assert len(segments) == touch_segment_count
        assert viewer.cursor().shape() != Qt.CursorShape.BlankCursor
        assert (
            viewer.interaction._pointer_input.active_device is PointerDeviceKind.TOUCH
        )
    finally:
        viewer.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize(
    ("elapsed_seconds", "expected_extra_stroke"),
    ((0.0, False), (1.0, True)),
    ids=("immediate-duplicate", "delayed-mouse"),
)
def test_unknown_synthesized_press_uses_time_fallback_after_touch(
    qapp,
    elapsed_seconds: float,
    expected_extra_stroke: bool,
) -> None:
    """Unknown button metadata must use the bounded compatibility-event window."""
    viewer = _touch_mask_viewer(qapp)
    position = QPointF(100.0, 100.0)
    touch_device = QTest.createTouchDevice()
    unknown_device = QPointingDevice(
        "Unknown synthesized pointer",
        704,
        QInputDevice.DeviceType.Unknown,
        QPointingDevice.PointerType.Generic,
        QInputDevice.Capability.Position,
        1,
        1,
    )
    try:
        tool = viewer._tools_manager.get_active_tool()
        segments = []
        tool.signals.stroke_applied.connect(segments.append)
        QTest.touchEvent(viewer, touch_device).press(
            0, position.toPoint(), viewer
        ).commit()
        QTest.touchEvent(viewer, touch_device).release(
            0, position.toPoint(), viewer
        ).commit()
        qapp.processEvents()
        touch_segment_count = len(segments)
        pointer_input = viewer.interaction._pointer_input
        assert pointer_input._last_touch_ended_at is not None
        pointer_input._last_touch_ended_at -= elapsed_seconds

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
            qapp.sendEvent(
                viewer,
                QMouseEvent(
                    event_type,
                    position,
                    position,
                    position,
                    button,
                    buttons,
                    Qt.KeyboardModifier.NoModifier,
                    Qt.MouseEventSource.MouseEventSynthesizedBySystem,
                    unknown_device,
                ),
            )

        expected_count = touch_segment_count + int(expected_extra_stroke)
        assert len(segments) == expected_count
        expected_device = (
            PointerDeviceKind.MOUSE
            if expected_extra_stroke
            else PointerDeviceKind.TOUCH
        )
        assert pointer_input.active_device is expected_device
    finally:
        viewer.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize(
    "source",
    (
        Qt.MouseEventSource.MouseEventSynthesizedByQt,
        Qt.MouseEventSource.MouseEventSynthesizedBySystem,
        Qt.MouseEventSource.MouseEventSynthesizedByApplication,
    ),
)
@pytest.mark.parametrize("metadata", ("mouse", "touchpad"))
def test_genuine_synthesized_hover_device_press_after_touch_paints(
    qapp,
    source: Qt.MouseEventSource,
    metadata: str,
) -> None:
    """Hover hardware metadata must win over the post-touch deduplication window."""
    viewer = _touch_mask_viewer(qapp)
    try:
        tool = viewer._tools_manager.get_active_tool()
        segments = []
        tool.signals.stroke_applied.connect(segments.append)
        touch_device = QTest.createTouchDevice()
        position = QPointF(100.0, 100.0)
        QTest.touchEvent(viewer, touch_device).press(
            0, position.toPoint(), viewer
        ).commit()
        QTest.touchEvent(viewer, touch_device).release(
            0, position.toPoint(), viewer
        ).commit()
        qapp.processEvents()
        touch_segment_count = len(segments)
        event_device = (
            None
            if metadata == "mouse"
            else QPointingDevice(
                "Synthetic touchpad",
                703,
                QInputDevice.DeviceType.TouchPad,
                QPointingDevice.PointerType.Generic,
                QInputDevice.Capability.Position
                | QInputDevice.Capability.Hover
                | QInputDevice.Capability.MouseEmulation,
                1,
                1,
            )
        )

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
            arguments = (
                event_type,
                position,
                position,
                position,
                button,
                buttons,
                Qt.KeyboardModifier.NoModifier,
                source,
            )
            event = (
                QMouseEvent(*arguments, event_device)
                if event_device is not None
                else QMouseEvent(*arguments)
            )
            assert event.pointingDevice().type() in {
                QInputDevice.DeviceType.Mouse,
                QInputDevice.DeviceType.TouchPad,
            }
            qapp.sendEvent(viewer, event)

        assert touch_segment_count == 1
        assert len(segments) == touch_segment_count + 1
        assert viewer.cursor().shape() != Qt.CursorShape.BlankCursor
        assert (
            viewer.interaction._pointer_input.active_device is PointerDeviceKind.MOUSE
        )
    finally:
        viewer.deleteLater()
        qapp.processEvents()
