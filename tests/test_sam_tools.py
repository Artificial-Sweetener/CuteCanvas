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

import uuid
from dataclasses import fields

import numpy as np
import pytest
from cutecanvas.coverage import CoverageCombineMode
from cutecanvas.sam.segmentation_request import (
    SmartSegmentationProduct,
    SmartSegmentationRequest,
)
from cutecanvas.tools.ports import SmartSegmentationInteractionPort
from cutecanvas.tools.smart_segmentation import SmartMaskTool, SmartSelectTool
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor
from qpane import PointerDeviceKind, PointerPhase, PointerSample


class _StubPromptProjection:
    """Project Smart Select points through deterministic test transforms."""

    def __init__(
        self,
        *,
        panel_to_source=lambda point: QPointF(point),
        source_to_panel=lambda point: QPointF(point),
    ) -> None:
        """Capture the projection callbacks and one stable raster identity."""
        self.resource_id = uuid.uuid4()
        self.scene_id = uuid.uuid4()
        self.layer_id = uuid.uuid4()
        self._panel_to_source = panel_to_source
        self._source_to_panel = source_to_panel

    def panel_to_source(self, point: QPoint | QPointF) -> QPointF | None:
        """Project a panel point into the test raster."""
        return self._panel_to_source(point)

    def source_to_panel(self, point: QPoint | QPointF) -> QPointF | None:
        """Project a raster point into the test panel."""
        return self._source_to_panel(point)


class _StubMouseEvent:
    def __init__(
        self,
        button: Qt.MouseButton,
        point: QPoint,
        modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier,
    ):
        self._button = button
        self._position = QPointF(point)
        self._modifiers = modifiers
        self.accepted = False

    def button(self) -> Qt.MouseButton:
        return self._button

    def position(self):
        return self._position

    def modifiers(self) -> Qt.KeyboardModifier:
        return self._modifiers

    def accept(self) -> None:
        self.accepted = True


class _StubWheelEvent:
    def __init__(self, point: QPoint, delta_y: int):
        self._position = QPointF(point)
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
        self.pens = []
        self.paths = []

    def save(self) -> None:
        self.saved = True

    def restore(self) -> None:
        self.restore_calls += 1

    def setPen(self, pen) -> None:
        self.pens.append(pen)

    def setBrush(self, _brush) -> None:
        return

    def setClipPath(self, _path, _operation) -> None:
        return

    def drawPath(self, path) -> None:
        self.paths.append(path)


def _drag_selection(tool: SmartSelectTool, start: QPoint, end: QPoint):
    press_event = _StubMouseEvent(Qt.MouseButton.LeftButton, start)
    tool.mousePressEvent(press_event)
    move_event = _StubMouseEvent(Qt.MouseButton.LeftButton, end)
    tool.mouseMoveEvent(move_event)
    return press_event, move_event


@pytest.fixture
def smart_select_tool(qapp):
    tool = SmartSelectTool()
    projection = _StubPromptProjection()
    tool.activate(
        SmartSegmentationInteractionPort(
            is_alt_held=lambda: False,
            get_min_selection_size=lambda: 4,
            resolve_prompt_projection=lambda: projection,
            panel_to_active_mask_point=lambda point: QPointF(point),
            get_active_mask_color=lambda: QColor(64, 160, 255),
        )
    )
    yield tool
    tool.deactivate()


def test_smart_select_emits_bbox_from_origin(smart_select_tool):
    emissions = []
    smart_select_tool.signals.smart_segmentation_requested.connect(emissions.append)
    press_event, move_event = _drag_selection(
        smart_select_tool, QPoint(0, 0), QPoint(10, 10)
    )
    release_event = _StubMouseEvent(Qt.MouseButton.LeftButton, QPoint(10, 10))
    smart_select_tool.mouseReleaseEvent(release_event)
    assert press_event.accepted
    assert move_event.accepted
    assert release_event.accepted
    assert len(emissions) == 1
    request = emissions[0]
    assert isinstance(request, SmartSegmentationRequest)
    assert request.product is SmartSegmentationProduct.PIXEL_SELECTION
    assert np.array_equal(request.bounds, np.array([0, 0, 10, 10]))
    assert request.erase is False


def test_smart_mask_emits_the_mask_captured_at_gesture_start(qapp) -> None:
    """Changing active masks after press cannot retarget generated coverage."""
    projection = _StubPromptProjection()
    first_mask_id = uuid.uuid4()
    current_mask_id = [first_mask_id]
    tool = SmartMaskTool()
    tool.activate(
        SmartSegmentationInteractionPort(
            resolve_prompt_projection=lambda: projection,
            get_min_selection_size=lambda: 4,
            get_active_mask_id=lambda: current_mask_id[0],
        )
    )
    emissions = []
    tool.signals.smart_segmentation_requested.connect(emissions.append)

    _drag_selection(tool, QPoint(0, 0), QPoint(12, 14))
    current_mask_id[0] = uuid.uuid4()
    tool.mouseReleaseEvent(_StubMouseEvent(Qt.MouseButton.LeftButton, QPoint(12, 14)))

    assert len(emissions) == 1
    assert emissions[0].product is SmartSegmentationProduct.MASK_COVERAGE
    assert emissions[0].mask_id == first_mask_id
    assert emissions[0].combine_mode is CoverageCombineMode.ADD


def test_smart_select_port_excludes_snapping_and_emits_raw_bounds(
    smart_select_tool,
) -> None:
    """SAM receives raw region coordinates and has no Smart Guide capability."""
    emissions = []
    smart_select_tool.signals.smart_segmentation_requested.connect(emissions.append)
    _drag_selection(smart_select_tool, QPoint(96, 97), QPoint(204, 203))
    smart_select_tool.mouseReleaseEvent(
        _StubMouseEvent(Qt.MouseButton.LeftButton, QPoint(204, 203))
    )

    assert "snapping" not in {
        field.name for field in fields(SmartSegmentationInteractionPort)
    }
    assert np.array_equal(emissions[0].bounds, np.array([96, 97, 204, 203]))


def test_smart_select_box_uses_raster_coordinates_not_mask_coordinates() -> None:
    """SAM prompts must describe the raster input even when mask geometry differs."""
    tool = SmartSelectTool()
    projection = _StubPromptProjection(
        panel_to_source=lambda point: QPointF(
            point.x() - 100,
            point.y() - 50,
        ),
        source_to_panel=lambda point: QPointF(
            point.x() + 100,
            point.y() + 50,
        ),
    )
    tool.activate(
        SmartSegmentationInteractionPort(
            is_alt_held=lambda: False,
            get_min_selection_size=lambda: 4,
            resolve_prompt_projection=lambda: projection,
            panel_to_active_mask_point=lambda point: QPointF(point),
        )
    )
    emissions = []
    tool.signals.smart_segmentation_requested.connect(emissions.append)

    _drag_selection(tool, QPoint(110, 60), QPoint(130, 80))
    tool.mouseReleaseEvent(_StubMouseEvent(Qt.MouseButton.LeftButton, QPoint(130, 80)))

    assert len(emissions) == 1
    assert np.array_equal(emissions[0].bounds, np.array([10, 10, 30, 30]))
    tool.deactivate()


def test_smart_select_accepts_direct_touch_drag(smart_select_tool) -> None:
    emissions = []
    smart_select_tool.signals.smart_segmentation_requested.connect(emissions.append)

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
    assert np.array_equal(emissions[0].bounds, np.array([2, 3, 20, 30]))


def test_smart_select_first_gesture_uses_pointer_alt_snapshot(
    smart_select_tool,
) -> None:
    """A focus transition cannot make the first modified selection additive."""

    emissions = []
    smart_select_tool.signals.smart_segmentation_requested.connect(emissions.append)
    press = _StubMouseEvent(
        Qt.MouseButton.LeftButton,
        QPoint(1, 2),
        Qt.KeyboardModifier.AltModifier,
    )
    release = _StubMouseEvent(
        Qt.MouseButton.LeftButton,
        QPoint(20, 30),
        Qt.KeyboardModifier.AltModifier,
    )

    smart_select_tool.mousePressEvent(press)
    smart_select_tool.mouseReleaseEvent(release)

    assert len(emissions) == 1
    assert emissions[0].erase is True


def test_smart_select_ignores_zero_area_selection(smart_select_tool):
    emissions = []
    smart_select_tool.signals.smart_segmentation_requested.connect(emissions.append)
    press_event = _StubMouseEvent(Qt.MouseButton.LeftButton, QPoint(5, 5))
    smart_select_tool.mousePressEvent(press_event)
    release_event = _StubMouseEvent(Qt.MouseButton.LeftButton, QPoint(5, 5))
    smart_select_tool.mouseReleaseEvent(release_event)
    assert press_event.accepted
    assert release_event.accepted
    assert emissions == []
    painter = _RecordingPainter()
    smart_select_tool.draw_overlay(painter)
    assert painter.paths == []


def test_smart_mask_wheel_blocks_zoom_when_point_missing(qapp):
    projection = _StubPromptProjection()
    smart_select_tool = SmartMaskTool()
    point_projection = [None]
    smart_select_tool.activate(
        SmartSegmentationInteractionPort(
            resolve_prompt_projection=lambda: projection,
            panel_to_active_mask_point=lambda _point: point_projection[0],
            get_active_mask_id=uuid.uuid4,
        )
    )
    adjustments = []
    smart_select_tool.signals.mask_component_adjustment_requested.connect(
        lambda point, grow: adjustments.append((point, grow))
    )
    wheel_event = _StubWheelEvent(QPoint(2, 3), 120)
    smart_select_tool.wheelEvent(wheel_event)
    assert wheel_event.accepted
    assert adjustments == []
    point_projection[0] = QPointF(4, 5)
    grow_event = _StubWheelEvent(QPoint(4, 5), 120)
    smart_select_tool.wheelEvent(grow_event)
    point_projection[0] = QPointF(6, 7)
    shrink_event = _StubWheelEvent(QPoint(6, 7), -120)
    smart_select_tool.wheelEvent(shrink_event)
    assert grow_event.accepted and shrink_event.accepted
    assert adjustments == [
        (QPoint(4, 5), True),
        (QPoint(6, 7), False),
    ]


def test_draw_overlay_matches_mask_colour(qapp):
    projection = _StubPromptProjection()
    smart_select_tool = SmartMaskTool()
    smart_select_tool.activate(
        SmartSegmentationInteractionPort(
            resolve_prompt_projection=lambda: projection,
            get_min_selection_size=lambda: 4,
            get_active_mask_color=lambda: QColor(64, 160, 255),
            get_active_mask_id=uuid.uuid4,
        )
    )
    painter = _RecordingPainter()
    _drag_selection(smart_select_tool, QPoint(1, 1), QPoint(6, 6))
    smart_select_tool.draw_overlay(painter)
    smart_select_tool.mouseReleaseEvent(
        _StubMouseEvent(Qt.MouseButton.LeftButton, QPoint(6, 6))
    )
    assert painter.saved is True
    assert painter.restore_calls == 1
    assert len(painter.paths) == 2
    assert painter.pens[0].color() == QColor(64, 160, 255)
    assert painter.pens[1].color() == QColor(Qt.GlobalColor.white)


def test_draw_overlay_uses_mask_colour_when_alt(qapp):
    projection = _StubPromptProjection()
    smart_select_tool = SmartMaskTool()
    smart_select_tool.activate(
        SmartSegmentationInteractionPort(
            is_alt_held=lambda: True,
            get_min_selection_size=lambda: 4,
            resolve_prompt_projection=lambda: projection,
            panel_to_active_mask_point=lambda point: QPointF(point),
            get_active_mask_color=lambda: QColor(64, 160, 255),
            get_active_mask_id=uuid.uuid4,
        )
    )
    painter = _RecordingPainter()
    _drag_selection(smart_select_tool, QPoint(2, 2), QPoint(8, 8))
    smart_select_tool.draw_overlay(painter)
    smart_select_tool.mouseReleaseEvent(
        _StubMouseEvent(Qt.MouseButton.LeftButton, QPoint(8, 8))
    )
    assert painter.pens[0].color() == QColor(64, 160, 255)
