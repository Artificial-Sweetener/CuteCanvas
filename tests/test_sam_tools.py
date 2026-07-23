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

import numpy as np
import pytest
from cutecanvas.masks.tools.smart_select import SmartSelectTool
from cutecanvas.tools.ports import SmartSelectionInteractionPort
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor
from qpane import PointerDeviceKind, PointerPhase, PointerSample


class _PointWrapper:
    def __init__(self, point: QPoint):
        self._point = point

    def toPoint(self) -> QPoint:
        return self._point


class _StubMouseEvent:
    def __init__(self, button: Qt.MouseButton, point: QPoint):
        self._button = button
        self._position = _PointWrapper(point)
        self.accepted = False

    def button(self) -> Qt.MouseButton:
        return self._button

    def position(self):
        return self._position

    def accept(self) -> None:
        self.accepted = True


class _StubWheelEvent:
    def __init__(self, point: QPoint, delta_y: int):
        self._position = _PointWrapper(point)
        self._delta_y = delta_y
        self.accepted = False

    def position(self):
        return self._position

    def angleDelta(self) -> QPoint:
        return QPoint(0, self._delta_y)

    def accept(self) -> None:
        self.accepted = True


class _RecordingPainter:
    def __init__(self):
        self.saved = False
        self.restore_calls = 0
        self.pen = None
        self.brush = None
        self.rects = []

    def save(self) -> None:
        self.saved = True

    def restore(self) -> None:
        self.restore_calls += 1

    def setPen(self, pen) -> None:
        self.pen = pen

    def setBrush(self, brush) -> None:
        self.brush = brush

    def drawRect(self, rect) -> None:
        self.rects.append(rect)


def _drag_selection(tool: SmartSelectTool, start: QPoint, end: QPoint):
    press_event = _StubMouseEvent(Qt.MouseButton.LeftButton, start)
    tool.mousePressEvent(press_event)
    move_event = _StubMouseEvent(Qt.MouseButton.LeftButton, end)
    tool.mouseMoveEvent(move_event)
    return press_event, move_event


@pytest.fixture
def smart_select_tool(qapp):
    tool = SmartSelectTool()
    tool.activate(
        SmartSelectionInteractionPort(
            is_alt_held=lambda: False,
            get_min_selection_size=lambda: 4,
            panel_to_content_point=lambda point: point,
            image_to_panel_point=lambda point: point,
            get_active_mask_color=lambda: QColor(64, 160, 255),
        )
    )
    yield tool
    tool.deactivate()


def test_smart_select_emits_bbox_from_origin(smart_select_tool):
    emissions = []
    smart_select_tool.signals.region_selected_for_masking.connect(
        lambda bbox, erase: emissions.append((bbox, erase))
    )
    press_event, move_event = _drag_selection(
        smart_select_tool, QPoint(0, 0), QPoint(10, 10)
    )
    release_event = _StubMouseEvent(Qt.MouseButton.LeftButton, QPoint(10, 10))
    smart_select_tool.mouseReleaseEvent(release_event)
    assert press_event.accepted
    assert move_event.accepted
    assert release_event.accepted
    assert len(emissions) == 1
    bbox, erase_flag = emissions[0]
    assert np.array_equal(bbox, np.array([0, 0, 10, 10]))
    assert erase_flag is False


def test_smart_select_accepts_direct_touch_drag(smart_select_tool) -> None:
    emissions = []
    smart_select_tool.signals.region_selected_for_masking.connect(
        lambda bbox, erase: emissions.append((bbox, erase))
    )

    def sample(phase: PointerPhase, point: QPointF) -> PointerSample:
        return PointerSample(
            pointer_id=1,
            device=PointerDeviceKind.TOUCH,
            phase=phase,
            position=point,
            global_position=point,
            pressure=1.0,
            buttons=Qt.MouseButton.NoButton,
            modifiers=Qt.KeyboardModifier.NoModifier,
            timestamp_ms=0,
        )

    assert smart_select_tool.handle_pointer_sample(
        sample(PointerPhase.BEGIN, QPointF(2.0, 3.0))
    )
    assert smart_select_tool.handle_pointer_sample(
        sample(PointerPhase.UPDATE, QPointF(20.0, 30.0))
    )
    assert smart_select_tool.handle_pointer_sample(
        sample(PointerPhase.END, QPointF(20.0, 30.0))
    )

    assert len(emissions) == 1
    assert np.array_equal(emissions[0][0], np.array([2, 3, 20, 30]))


def test_smart_select_ignores_zero_area_selection(smart_select_tool):
    emissions = []
    smart_select_tool.signals.region_selected_for_masking.connect(
        lambda bbox, erase: emissions.append((bbox, erase))
    )
    press_event = _StubMouseEvent(Qt.MouseButton.LeftButton, QPoint(5, 5))
    smart_select_tool.mousePressEvent(press_event)
    release_event = _StubMouseEvent(Qt.MouseButton.LeftButton, QPoint(5, 5))
    smart_select_tool.mouseReleaseEvent(release_event)
    assert press_event.accepted
    assert release_event.accepted
    assert emissions == []
    start, end = smart_select_tool.get_selection_points()
    assert start is None and end is None


def test_smart_select_wheel_blocks_zoom_when_point_missing(smart_select_tool):
    adjustments = []
    smart_select_tool.signals.mask_component_adjustment_requested.connect(
        lambda point, grow: adjustments.append((point, grow))
    )
    smart_select_tool._panel_to_content_point = lambda _: None
    wheel_event = _StubWheelEvent(QPoint(2, 3), 120)
    smart_select_tool.wheelEvent(wheel_event)
    assert wheel_event.accepted
    assert adjustments == []
    smart_select_tool._panel_to_content_point = lambda point: point
    grow_event = _StubWheelEvent(QPoint(4, 5), 120)
    smart_select_tool.wheelEvent(grow_event)
    shrink_event = _StubWheelEvent(QPoint(6, 7), -120)
    smart_select_tool.wheelEvent(shrink_event)
    assert grow_event.accepted and shrink_event.accepted
    assert adjustments == [
        (QPoint(4, 5), True),
        (QPoint(6, 7), False),
    ]


def test_draw_overlay_matches_mask_colour(smart_select_tool):
    painter = _RecordingPainter()
    _drag_selection(smart_select_tool, QPoint(1, 1), QPoint(6, 6))
    smart_select_tool.draw_overlay(painter)
    smart_select_tool.mouseReleaseEvent(
        _StubMouseEvent(Qt.MouseButton.LeftButton, QPoint(6, 6))
    )
    assert painter.saved is True
    assert painter.restore_calls == 1
    assert painter.pen is not None
    assert painter.pen.style() == Qt.PenStyle.DotLine
    assert painter.brush == Qt.BrushStyle.NoBrush
    assert painter.pen.color() == QColor(64, 160, 255)


def test_draw_overlay_uses_mask_colour_when_alt(smart_select_tool):
    smart_select_tool.activate(
        SmartSelectionInteractionPort(
            is_alt_held=lambda: True,
            get_min_selection_size=lambda: 4,
            panel_to_content_point=lambda point: point,
            image_to_panel_point=lambda point: point,
            get_active_mask_color=lambda: QColor(64, 160, 255),
        )
    )
    painter = _RecordingPainter()
    _drag_selection(smart_select_tool, QPoint(2, 2), QPoint(8, 8))
    smart_select_tool.draw_overlay(painter)
    smart_select_tool.mouseReleaseEvent(
        _StubMouseEvent(Qt.MouseButton.LeftButton, QPoint(8, 8))
    )
    assert painter.pen.color() == QColor(64, 160, 255)
