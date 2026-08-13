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
"""Tests for affine transform input translation."""

import uuid

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent

from cutecanvas.editor.transform_interaction import TransformBoxPresentation
from cutecanvas.tools.affine_ports import TransformInteractionPort
from cutecanvas.tools.transform import TransformTool
from qpane import PointerDeviceKind, PointerPhase, PointerSample
from qpane.scene.transform_geometry import (
    TransformHandle,
    TransformOperation,
    TransformOperationKind,
)


def test_mouse_operations_resolve_handles_body_rotation_and_resolution() -> None:
    """Mouse hit testing and standard resolution keys should match the contract."""
    calls: list[tuple[str, object]] = []
    tool = TransformTool()
    tool.activate(_port(calls))

    _drag(tool, QPointF(0, 0), QPointF(-20, -10), Qt.ShiftModifier)
    operation = calls[0][1]
    assert isinstance(operation, TransformOperation)
    assert operation == TransformOperation(
        TransformOperationKind.SCALE,
        TransformHandle.TOP_LEFT,
    )
    modifiers = next(value for name, value in calls if name == "update")
    assert not modifiers.proportional
    assert not any(name == "commit" for name, _value in calls)

    calls.clear()
    _drag(tool, QPointF(50, 50), QPointF(65, 60))
    assert calls[0][1] == TransformOperation(TransformOperationKind.MOVE)

    calls.clear()
    _drag(tool, QPointF(120, 20), QPointF(125, 35), Qt.ShiftModifier)
    assert calls[0][1] == TransformOperation(TransformOperationKind.ROTATE)
    modifiers = next(value for name, value in calls if name == "update")
    assert modifiers.snap_rotation

    enter = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.NoModifier)
    tool.keyPressEvent(enter)
    assert ("commit", True) in calls

    escape = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.NoModifier)
    tool.keyPressEvent(escape)
    assert ("cancel", True) in calls


def test_ctrl_shift_side_handle_selects_skew_and_alt_uses_center() -> None:
    """Side-handle modifiers should map to skew and center-origin policy."""
    calls: list[tuple[str, object]] = []
    tool = TransformTool()
    tool.activate(_port(calls))
    modifiers = Qt.ControlModifier | Qt.ShiftModifier | Qt.AltModifier

    _drag(tool, QPointF(50, 0), QPointF(65, 0), modifiers)

    assert calls[0][1] == TransformOperation(
        TransformOperationKind.SKEW,
        TransformHandle.TOP,
    )
    update = next(value for name, value in calls if name == "update")
    assert update.about_center


def test_normalized_pen_sequence_uses_the_same_transform_path() -> None:
    """Active-pen input must not bypass affine session ownership."""
    calls: list[tuple[str, object]] = []
    tool = TransformTool()
    tool.activate(_port(calls))

    for phase, point in (
        (PointerPhase.BEGIN, QPointF(100, 100)),
        (PointerPhase.UPDATE, QPointF(120, 115)),
        (PointerPhase.END, QPointF(120, 115)),
    ):
        assert tool.handle_pointer_sample(_sample(phase, point))

    assert calls[0][1] == TransformOperation(
        TransformOperationKind.SCALE,
        TransformHandle.BOTTOM_RIGHT,
    )
    assert [name for name, _value in calls].count("end") == 1


def _port(calls: list[tuple[str, object]]) -> TransformInteractionPort:
    """Build an observable transform boundary around one fixed box."""
    return TransformInteractionPort(
        transform_presentation=_presentation,
        begin_transform=lambda operation, _point: (
            calls.append(("begin", operation)) or True
        ),
        update_transform=lambda _point, modifiers: (
            calls.append(("update", modifiers)) or True
        ),
        end_transform_gesture=lambda _point, modifiers: (
            calls.append(("end", modifiers)) or True
        ),
        commit_transform=lambda: calls.append(("commit", True)) or True,
        cancel_transform=lambda: calls.append(("cancel", True)) or True,
        suspend_transform=lambda: calls.append(("suspend", True)) or True,
    )


def _presentation() -> TransformBoxPresentation:
    """Return a 100-pixel square with all eight edit points."""
    points = {
        TransformHandle.TOP_LEFT: QPointF(0, 0),
        TransformHandle.TOP: QPointF(50, 0),
        TransformHandle.TOP_RIGHT: QPointF(100, 0),
        TransformHandle.RIGHT: QPointF(100, 50),
        TransformHandle.BOTTOM_RIGHT: QPointF(100, 100),
        TransformHandle.BOTTOM: QPointF(50, 100),
        TransformHandle.BOTTOM_LEFT: QPointF(0, 100),
        TransformHandle.LEFT: QPointF(0, 50),
    }
    return TransformBoxPresentation(
        uuid.uuid4(),
        uuid.uuid4(),
        (
            points[TransformHandle.TOP_LEFT],
            points[TransformHandle.TOP_RIGHT],
            points[TransformHandle.BOTTOM_RIGHT],
            points[TransformHandle.BOTTOM_LEFT],
        ),
        tuple(points.items()),
        QPointF(50, 50),
        True,
    )


def _drag(
    tool: TransformTool,
    start: QPointF,
    end: QPointF,
    modifiers: Qt.KeyboardModifier = Qt.NoModifier,
) -> None:
    """Drive one mouse drag through the normal tool event surface."""
    tool.mousePressEvent(
        _mouse(
            QEvent.Type.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton, modifiers
        )
    )
    tool.mouseMoveEvent(
        _mouse(QEvent.Type.MouseMove, end, Qt.NoButton, Qt.LeftButton, modifiers)
    )
    tool.mouseReleaseEvent(
        _mouse(
            QEvent.Type.MouseButtonRelease, end, Qt.LeftButton, Qt.NoButton, modifiers
        )
    )


def _mouse(
    event_type: QEvent.Type,
    point: QPointF,
    button: Qt.MouseButton,
    buttons: Qt.MouseButton,
    modifiers: Qt.KeyboardModifier,
) -> QMouseEvent:
    """Build one detached mouse event."""
    return QMouseEvent(event_type, point, point, point, button, buttons, modifiers)


def _sample(phase: PointerPhase, point: QPointF) -> PointerSample:
    """Build one normalized active-pen sample."""
    return PointerSample(
        pointer_id=1,
        device=PointerDeviceKind.PEN,
        phase=phase,
        position=point,
        global_position=point,
        pressure=1.0,
        buttons=Qt.LeftButton,
        modifiers=Qt.NoModifier,
        timestamp_ms=0,
    )
