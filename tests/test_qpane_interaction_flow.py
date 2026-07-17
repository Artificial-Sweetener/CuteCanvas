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

"""Tests for qpane interaction flows and event handling."""

import types
import uuid
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QEnterEvent, QImage, QKeyEvent, QWheelEvent
from qpane import QPane


def _cleanup_qpane(qpane, qapp):
    qpane.deleteLater()
    qapp.processEvents()


def _make_images(colors):
    images = []
    for color in colors:
        image = QImage(32, 32, QImage.Format_ARGB32)
        image.fill(color)
        images.append(image)
    return images


def _load_images(qpane, colors):
    image_ids = [uuid.uuid4() for _ in colors]
    images = _make_images(colors)
    image_map = QPane.imageMapFromLists(
        images, paths=[None] * len(images), ids=image_ids
    )
    qpane.setImagesByID(image_map, image_ids[0])
    return image_ids


@pytest.mark.parametrize(
    "key, attr",
    [(Qt.Key_Alt, "alt_key_held"), (Qt.Key_Shift, "shift_key_held")],
)
def test_modifier_keys_toggle_internal_state(qapp, key, attr):
    qpane = QPane(features=())
    qpane.resize(64, 64)
    _load_images(qpane, [Qt.white])
    try:
        pressed = QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier)
        released = QKeyEvent(QEvent.KeyRelease, key, Qt.NoModifier)
        qpane.keyPressEvent(pressed)
        assert getattr(qpane.interaction, attr) is True
        qpane.keyReleaseEvent(released)
        assert getattr(qpane.interaction, attr) is False
    finally:
        _cleanup_qpane(qpane, qapp)


def test_wheel_event_routes_to_tool_manager(qapp, monkeypatch):
    qpane = QPane(features=())
    qpane.resize(64, 64)
    _load_images(qpane, [Qt.white])
    try:
        received = []

        def recorder(self, event):
            received.append(event)

        tool_manager = qpane._tools_manager
        monkeypatch.setattr(
            tool_manager,
            "wheelEvent",
            types.MethodType(recorder, tool_manager),
        )
        event = QWheelEvent(
            QPointF(10, 10),
            QPointF(10, 10),
            QPoint(0, 0),
            QPoint(0, 120),
            Qt.NoButton,
            Qt.NoModifier,
            Qt.ScrollPhase.ScrollUpdate,
            False,
            Qt.MouseEventSource.MouseEventNotSynthesized,
        )
        qpane.wheelEvent(event)
        assert received and received[0] is event
    finally:
        _cleanup_qpane(qpane, qapp)


def test_enter_and_leave_events_delegate_to_tool_manager(qapp, monkeypatch):
    qpane = QPane(features=())
    qpane.resize(64, 64)
    _load_images(qpane, [Qt.white])
    try:
        calls = []

        def record_enter(self, event):
            calls.append(("enter", event))

        def record_leave(self, event):
            calls.append(("leave", event))

        tool_manager = qpane._tools_manager
        monkeypatch.setattr(
            tool_manager,
            "enterEvent",
            types.MethodType(record_enter, tool_manager),
        )
        monkeypatch.setattr(
            tool_manager,
            "leaveEvent",
            types.MethodType(record_leave, tool_manager),
        )
        qpane.enterEvent(QEnterEvent(QPointF(0, 0), QPointF(0, 0), QPointF(0, 0)))
        qpane.leaveEvent(QEvent(QEvent.Type.Leave))
        assert [call[0] for call in calls] == ["enter", "leave"]
    finally:
        _cleanup_qpane(qpane, qapp)


def test_control_mode_selected_before_show_is_preserved(qapp) -> None:
    """An explicit host selection should win over first-show initialization."""
    qpane = QPane(features=())
    qpane.resize(64, 64)
    _load_images(qpane, [Qt.white])
    try:
        qpane.setControlMode(QPane.CONTROL_MODE_CURSOR)

        qpane.show()
        qapp.processEvents()

        assert qpane.getControlMode() == QPane.CONTROL_MODE_CURSOR
    finally:
        _cleanup_qpane(qpane, qapp)


def test_set_current_image_id_suspends_overlays(qapp, monkeypatch):
    qpane = QPane(features=())
    qpane.resize(64, 64)
    image_ids = _load_images(qpane, [Qt.white, Qt.black])
    try:
        next_id = image_ids[1]
        delegate = qpane.swapDelegate
        captured = []

        def fake_set_current_image(self, image_id, *, fit_view=None, save_view=True):
            captured.append(
                (
                    qpane.interaction.overlays_suspended,
                    qpane.interaction.overlays_resume_pending,
                    image_id,
                    save_view,
                )
            )

        monkeypatch.setattr(
            delegate,
            "set_current_image",
            types.MethodType(fake_set_current_image, delegate),
        )
        qpane.setCurrentImageID(next_id)
        assert captured == [(True, True, next_id, True)]
        qpane.resumeOverlays()
        assert qpane.interaction.overlays_suspended is False
        assert qpane.interaction.overlays_resume_pending is False
    finally:
        _cleanup_qpane(qpane, qapp)


def test_blank_forwards_to_delegate(qapp, monkeypatch):
    qpane = QPane(features=())
    qpane.resize(64, 64)
    _load_images(qpane, [Qt.white])
    try:
        called = []

        def fake_blank(self):
            called.append("blank")

        monkeypatch.setattr(type(qpane.interaction), "blank", fake_blank, raising=False)
        qpane.blank()
        assert called == ["blank"]
    finally:
        _cleanup_qpane(qpane, qapp)


def test_resume_helpers_forward_to_delegate(qapp, monkeypatch):
    qpane = QPane(features=())
    try:
        calls: dict[str, int] = {"resume": 0, "resume_update": 0, "maybe": 0}

        def fake_resume(self):
            calls["resume"] += 1

        def fake_resume_update(self):
            calls["resume_update"] += 1

        def fake_maybe(self):
            calls["maybe"] += 1

        monkeypatch.setattr(
            type(qpane.interaction),
            "resume_overlays",
            fake_resume,
            raising=False,
        )
        monkeypatch.setattr(
            type(qpane.interaction),
            "resume_overlays_and_update",
            fake_resume_update,
            raising=False,
        )
        monkeypatch.setattr(
            type(qpane.interaction),
            "maybe_resume_overlays",
            fake_maybe,
            raising=False,
        )
        qpane.resumeOverlays()
        qpane.resumeOverlaysAndUpdate()
        qpane.maybeResumeOverlays()
        assert calls == {"resume": 1, "resume_update": 1, "maybe": 1}
    finally:
        _cleanup_qpane(qpane, qapp)
