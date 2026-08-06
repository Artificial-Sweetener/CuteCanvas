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

"""Tests for mask tool interactions and signals."""

import math
import uuid

import numpy as np
import pytest
from cutecanvas.masks.stroke_preview import DecimatedStrokePreview
from cutecanvas.painting import BrushStrokeSegment
from cutecanvas.painting.rendering import render_coverage_stroke
from cutecanvas.painting.tools import BrushTool, EraserTool
from cutecanvas.tools.ports import PaintingInteractionPort
from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from qpane import PointerDeviceKind, PointerPhase, PointerSample
from qpane.raster.image_conversion import qimage_to_numpy_view_grayscale8
from qpane.rendering.coordinates import PanelHitTest


class _WheelEventStub:
    def __init__(self, pixel: QPoint | None = None, angle: QPoint | None = None):
        self._pixel = pixel or QPoint(0, 0)
        self._angle = angle or QPoint(0, 0)
        self.accepted = False

    def pixelDelta(self) -> QPoint:
        return self._pixel

    def angleDelta(self) -> QPoint:
        return self._angle

    def accept(self) -> None:
        self.accepted = True


class _PositionStub:
    def __init__(self, point: QPoint):
        self._point = point

    def toPoint(self) -> QPoint:
        return self._point


class _MouseEventStub:
    def __init__(
        self,
        point: QPoint,
        button: Qt.MouseButton = Qt.MouseButton.LeftButton,
        modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier,
    ):
        self._point = point
        self._button = button
        self._modifiers = modifiers
        self.accepted = False

    def button(self) -> Qt.MouseButton:
        return self._button

    def position(self):
        return _PositionStub(self._point)

    def modifiers(self) -> Qt.KeyboardModifier:
        return self._modifiers

    def accept(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.accepted = False


def _record_segment(
    strokes: list[tuple[QPoint, QPoint, bool]],
    segment: BrushStrokeSegment,
) -> None:
    """Convert one payload to the integer tuple used by mouse characterizations."""
    strokes.append(
        (
            QPoint(round(segment.start[0]), round(segment.start[1])),
            QPoint(round(segment.end[0]), round(segment.end[1])),
            segment.erase,
        )
    )


def _pointer_sample(
    phase: PointerPhase,
    position: QPointF,
    *,
    pressure: float,
    device: PointerDeviceKind = PointerDeviceKind.PEN,
) -> PointerSample:
    """Build a normalized direct-input sample for brush tests."""
    return PointerSample(
        pointer_id=17,
        device=device,
        phase=phase,
        position=QPointF(position),
        global_position=QPointF(position),
        pressure=pressure,
        buttons=(
            Qt.MouseButton.NoButton
            if phase in (PointerPhase.END, PointerPhase.HOVER)
            else Qt.MouseButton.LeftButton
        ),
        modifiers=Qt.KeyboardModifier.NoModifier,
        timestamp_ms=0,
    )


def _snapshot_array_region(
    pixels: np.ndarray,
    region: QRect,
    stride: int,
) -> np.ndarray:
    """Copy one zero-origin storage region at the requested preview stride."""
    return pixels[
        region.top() : region.bottom() + 1 : stride,
        region.left() : region.right() + 1 : stride,
    ].copy()


def test_decimated_stroke_state_tracks_stride_and_dirty_rect():
    state = DecimatedStrokePreview(mask_id=uuid.uuid4(), stride=2)
    mask_view = np.zeros((8, 8), dtype=np.uint8)
    dirty_rect = QRect(QPoint(0, 0), QPoint(3, 3))
    start = QPoint(0, 0)
    end = QPoint(3, 3)
    preview = state.preview_segment(
        dirty_rect=dirty_rect,
        segment=BrushStrokeSegment.fixed(
            (start.x(), start.y()), (end.x(), end.y()), 4, False
        ),
        snapshot_region=lambda region, stride: _snapshot_array_region(
            mask_view, region, stride
        ),
    )
    assert state._dirty_rect == dirty_rect
    assert preview.rect == dirty_rect
    assert preview.image.text("qpane_preview_stride") == "2"
    assert preview.image.text("qpane_preview_provisional") == "1"
    preview_view, _ = qimage_to_numpy_view_grayscale8(preview.image)
    height = dirty_rect.bottom() - dirty_rect.top() + 1
    width = dirty_rect.right() - dirty_rect.left() + 1
    expected_height = math.ceil(height / state.stride)
    expected_width = math.ceil(width / state.stride)
    assert preview_view.shape == (expected_height, expected_width)
    assert np.any(preview_view > 0)
    second_rect = QRect(QPoint(2, 2), QPoint(4, 4))
    accumulated_preview = state.preview_segment(
        dirty_rect=second_rect,
        segment=BrushStrokeSegment.fixed((2, 2), (4, 4), 4, True),
        snapshot_region=lambda region, stride: _snapshot_array_region(
            mask_view, region, stride
        ),
    )
    accumulated_rect = dirty_rect.united(second_rect)
    assert state._dirty_rect == accumulated_rect
    assert accumulated_preview.rect == second_rect
    assert len(state._segments) == 2
    full_preview = state.current_preview(
        lambda region, stride: _snapshot_array_region(mask_view, region, stride)
    )
    assert full_preview is not None
    assert full_preview.rect == accumulated_rect
    full_pixels, _ = qimage_to_numpy_view_grayscale8(full_preview.image)
    _, expected_preview = render_coverage_stroke(
        before=_snapshot_array_region(mask_view, accumulated_rect, 1),
        dirty_rect=accumulated_rect,
        segments=tuple(state._segments),
        preview_stride=state.stride,
    )
    expected_pixels, _ = qimage_to_numpy_view_grayscale8(expected_preview)
    np.testing.assert_array_equal(
        full_pixels,
        expected_pixels,
    )


@pytest.mark.parametrize("brush_size", [3, 5, 6, 11])
def test_preview_matches_worker_single_point(brush_size):
    state = DecimatedStrokePreview(mask_id=uuid.uuid4(), stride=1)
    mask_view = np.zeros((64, 64), dtype=np.uint8)
    start = QPoint(10, 12)
    stroke_rect = QRect(start, start).normalized()
    margin = int(brush_size / 2) + 2
    dirty_rect = stroke_rect.adjusted(-margin, -margin, margin, margin)
    preview = state.preview_segment(
        dirty_rect=dirty_rect,
        segment=BrushStrokeSegment.fixed(
            (start.x(), start.y()), (start.x(), start.y()), brush_size, False
        ),
        snapshot_region=lambda region, stride: _snapshot_array_region(
            mask_view, region, stride
        ),
    )
    preview_view, _ = qimage_to_numpy_view_grayscale8(preview.image)
    y0, x0 = dirty_rect.top(), dirty_rect.left()
    y1, x1 = dirty_rect.bottom() + 1, dirty_rect.right() + 1
    before_slice = mask_view[y0:y1, x0:x1]
    segment = BrushStrokeSegment.fixed(
        start=(int(start.x()), int(start.y())),
        end=(int(start.x()), int(start.y())),
        diameter=brush_size,
        erase=False,
    )
    after_slice, _ = render_coverage_stroke(
        before=before_slice,
        dirty_rect=dirty_rect,
        segments=(segment,),
    )
    assert preview_view.shape == after_slice.shape
    np.testing.assert_array_equal(preview_view, after_slice)


def test_brush_tool_wheel_clamps_and_grows(qapp):
    tool = BrushTool()
    brush_size = 2
    emitted_sizes: list[int] = []

    def get_brush_size() -> int:
        return brush_size

    def on_size_changed(value: int) -> None:
        nonlocal brush_size
        brush_size = value
        emitted_sizes.append(value)

    tool.activate(
        PaintingInteractionPort(
            get_brush_size=get_brush_size, get_brush_increment=lambda: 5
        )
    )
    tool.signals.brush_size_changed.connect(on_size_changed)
    negative_event = _WheelEventStub(pixel=QPoint(0, -1))
    tool.wheelEvent(negative_event)
    assert negative_event.accepted
    positive_event = _WheelEventStub(pixel=QPoint(0, 1))
    tool.wheelEvent(positive_event)
    assert positive_event.accepted
    assert emitted_sizes == [1, 6]


def test_brush_tool_preserves_pen_pressure_and_subpixel_samples(qapp) -> None:
    tool = BrushTool()
    tool.activate(
        PaintingInteractionPort(
            get_brush_size=lambda: 40,
            panel_hit_test_precise=lambda point: PanelHitTest(
                panel_point=point.toPoint(),
                raw_point=QPointF(point),
                clamped_point=point.toPoint(),
                inside_image=True,
            ),
            get_image_rect=lambda: QRect(0, 0, 100, 100),
            get_pen_pressure_min_ratio=lambda: 0.15,
            get_pen_pressure_gamma=lambda: 1.0,
            get_pen_pressure_enabled=lambda: True,
        )
    )
    segments: list[BrushStrokeSegment] = []
    undo_events: list[None] = []
    completed_events: list[None] = []
    tool.signals.stroke_applied.connect(segments.append)
    tool.signals.undo_state_push_requested.connect(lambda: undo_events.append(None))
    tool.signals.stroke_completed.connect(lambda: completed_events.append(None))

    assert tool.handle_pointer_sample(
        _pointer_sample(PointerPhase.BEGIN, QPointF(10.25, 20.75), pressure=0.25)
    )
    assert tool.handle_pointer_sample(
        _pointer_sample(PointerPhase.UPDATE, QPointF(20.75, 30.125), pressure=1.0)
    )
    assert tool.handle_pointer_sample(
        _pointer_sample(PointerPhase.END, QPointF(20.75, 30.125), pressure=0.0)
    )

    assert segments[0].start == (10.25, 20.75)
    assert segments[0].start_diameter == pytest.approx(14.5)
    assert segments[1].end == (20.75, 30.125)
    assert segments[1].start_diameter == pytest.approx(14.5)
    assert segments[1].end_diameter == pytest.approx(40.0)
    assert len(undo_events) == 1
    assert len(completed_events) == 1


def test_brush_tool_pen_hover_previews_nominal_size_without_painting(qapp) -> None:
    tool = BrushTool()
    tool.activate(
        PaintingInteractionPort(
            get_brush_size=lambda: 40,
            panel_hit_test_precise=lambda point: PanelHitTest(
                panel_point=point.toPoint(),
                raw_point=QPointF(point),
                clamped_point=point.toPoint(),
                inside_image=True,
            ),
            get_image_rect=lambda: QRect(0, 0, 100, 100),
            get_zoom=lambda: 2.0,
            get_dpr=lambda: 2.0,
            get_preview_color=lambda: QColor(Qt.GlobalColor.red),
        )
    )
    segments: list[BrushStrokeSegment] = []
    undo_events: list[None] = []
    tool.signals.stroke_applied.connect(segments.append)
    tool.signals.undo_state_push_requested.connect(lambda: undo_events.append(None))

    assert tool.handle_pointer_sample(
        _pointer_sample(PointerPhase.HOVER, QPointF(30.25, 30.75), pressure=0.0)
    )

    preview = tool.pointer_preview
    assert preview is not None
    assert preview.position == QPointF(30.25, 30.75)
    assert preview.diameter == pytest.approx(40.0)
    assert preview.contact is False
    assert preview.erase is False
    assert segments == []
    assert undo_events == []

    canvas = QImage(80, 80, QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(Qt.GlobalColor.white)
    painter = QPainter(canvas)
    tool.draw_overlay(painter)
    painter.end()

    assert canvas.pixelColor(50, 31) != QColor(Qt.GlobalColor.white)
    assert canvas.pixelColor(30, 31) == QColor(Qt.GlobalColor.white)


def test_brush_tool_contact_preview_matches_pressure_diameter(qapp) -> None:
    tool = BrushTool()
    tool.activate(
        PaintingInteractionPort(
            get_brush_size=lambda: 40,
            panel_to_content_point=lambda point: point,
            get_pen_pressure_min_ratio=lambda: 0.15,
            get_pen_pressure_gamma=lambda: 1.0,
            get_pen_pressure_enabled=lambda: True,
        )
    )

    assert tool.handle_pointer_sample(
        _pointer_sample(PointerPhase.BEGIN, QPointF(10.0, 20.0), pressure=0.25)
    )

    preview = tool.pointer_preview
    assert preview is not None
    assert preview.diameter == pytest.approx(14.5)
    assert preview.contact is True


def test_brush_tool_eraser_hover_previews_erase_state(qapp) -> None:
    tool = BrushTool()
    tool.activate(
        PaintingInteractionPort(
            get_brush_size=lambda: 20,
            panel_to_content_point=lambda point: point,
        )
    )

    assert tool.handle_pointer_sample(
        _pointer_sample(
            PointerPhase.HOVER,
            QPointF(5.0, 5.0),
            pressure=0.0,
            device=PointerDeviceKind.ERASER,
        )
    )

    preview = tool.pointer_preview
    assert preview is not None
    assert preview.erase is True


def test_brush_first_mouse_stroke_uses_pointer_alt_snapshot(qapp) -> None:
    """A missed key press cannot make the first physically modified stroke paint."""

    tool = BrushTool()
    tool.activate(
        PaintingInteractionPort(
            is_alt_held=lambda: False,
            panel_to_content_point=lambda point: point,
        )
    )
    segments: list[BrushStrokeSegment] = []
    tool.signals.stroke_applied.connect(segments.append)

    event = _MouseEventStub(
        QPoint(5, 5),
        modifiers=Qt.KeyboardModifier.AltModifier,
    )
    tool.mousePressEvent(event)

    assert event.accepted
    assert segments
    assert segments[0].erase is True


@pytest.mark.parametrize(
    "modifiers",
    [Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.AltModifier],
)
def test_explicit_eraser_never_inverts_to_paint(qapp, modifiers) -> None:
    """The persistent eraser must erase with or without transient Alt."""

    tool = EraserTool()
    tool.activate(
        PaintingInteractionPort(
            is_alt_held=lambda: bool(modifiers & Qt.KeyboardModifier.AltModifier),
            panel_to_content_point=lambda point: point,
        )
    )
    segments: list[BrushStrokeSegment] = []
    tool.signals.stroke_applied.connect(segments.append)

    event = _MouseEventStub(QPoint(5, 5), modifiers=modifiers)
    tool.mousePressEvent(event)

    assert event.accepted
    assert segments and segments[0].erase is True
    assert not tool.supports_alt_erase_indicator


def test_brush_tool_bounds_hover_repaints_to_old_and_new_ring_extents(qapp) -> None:
    updates: list[QRect] = []
    tool = BrushTool()
    tool.activate(
        PaintingInteractionPort(
            get_brush_size=lambda: 20,
            panel_to_content_point=lambda point: point,
            get_zoom=lambda: 2.0,
            get_dpr=lambda: 2.0,
            request_overlay_update=updates.append,
        )
    )

    assert tool.handle_pointer_sample(
        _pointer_sample(PointerPhase.HOVER, QPointF(20.0, 20.0), pressure=0.0)
    )
    assert tool.handle_pointer_sample(
        _pointer_sample(PointerPhase.HOVER, QPointF(50.0, 20.0), pressure=0.0)
    )

    assert len(updates) == 2
    assert updates[0].contains(QPoint(10, 20))
    assert updates[1].contains(QPoint(10, 20))
    assert updates[1].contains(QPoint(60, 20))


def test_brush_tool_eraser_tip_overrides_modifier_mode(qapp) -> None:
    tool = BrushTool()
    tool.activate(
        PaintingInteractionPort(
            get_brush_size=lambda: 20,
            panel_to_content_point=lambda point: point,
        )
    )
    segments: list[BrushStrokeSegment] = []
    tool.signals.stroke_applied.connect(segments.append)

    assert tool.handle_pointer_sample(
        _pointer_sample(
            PointerPhase.BEGIN,
            QPointF(5.0, 5.0),
            pressure=0.5,
            device=PointerDeviceKind.ERASER,
        )
    )
    assert tool.handle_pointer_sample(
        _pointer_sample(
            PointerPhase.END,
            QPointF(5.0, 5.0),
            pressure=0.0,
            device=PointerDeviceKind.ERASER,
        )
    )

    assert segments[0].erase


def test_brush_tool_cancel_discards_session_without_completing(qapp) -> None:
    tool = BrushTool()
    tool.activate(
        PaintingInteractionPort(
            get_brush_size=lambda: 20,
            panel_to_content_point=lambda point: point,
        )
    )
    cancelled: list[None] = []
    completed: list[None] = []
    tool.signals.stroke_cancelled.connect(lambda: cancelled.append(None))
    tool.signals.stroke_completed.connect(lambda: completed.append(None))

    assert tool.handle_pointer_sample(
        _pointer_sample(PointerPhase.BEGIN, QPointF(5.0, 5.0), pressure=0.5)
    )
    assert tool.cancel_pointer_stroke()

    assert cancelled == [None]
    assert completed == []
    assert not tool.is_drawing


def test_brush_tool_straight_line_shift_mode(qapp):
    tool = BrushTool()
    shift_state = False

    def is_shift_held() -> bool:
        return shift_state

    tool.activate(
        PaintingInteractionPort(
            is_shift_held=is_shift_held,
            panel_to_content_point=lambda point: point,
            image_to_panel_point=lambda point: point,
        )
    )
    strokes: list[tuple[QPoint, QPoint, bool]] = []
    undo_events: list[None] = []
    tool.signals.stroke_applied.connect(
        lambda segment: _record_segment(strokes, segment)
    )
    tool.signals.undo_state_push_requested.connect(lambda: undo_events.append(None))
    first_point = QPoint(10, 10)
    first_press = _MouseEventStub(first_point)
    tool.mousePressEvent(first_press)
    assert first_press.accepted
    release_event = _MouseEventStub(first_point)
    tool.mouseReleaseEvent(release_event)
    shift_state = True
    second_point = QPoint(20, 20)
    second_press = _MouseEventStub(second_point)
    tool.mousePressEvent(second_press)
    assert second_press.accepted
    assert strokes == [
        (first_point, first_point, False),
        (first_point, second_point, False),
    ]
    assert len(undo_events) == 2
    assert tool.last_paint_anchor_point is not None
    assert tool.last_paint_anchor_point.raw == second_point
    assert tool.is_drawing is False
    assert tool.current_preview_point is None


def test_brush_tool_continuous_stroke_emits_segments(qapp):
    tool = BrushTool()
    alt_state = True

    def is_alt_held() -> bool:
        return alt_state

    tool.activate(
        PaintingInteractionPort(
            is_alt_held=is_alt_held,
            panel_to_content_point=lambda point: point,
        )
    )
    strokes: list[tuple[QPoint, QPoint, bool]] = []
    undo_events: list[None] = []
    completed_events: list[None] = []
    tool.signals.stroke_applied.connect(
        lambda segment: _record_segment(strokes, segment)
    )
    tool.signals.undo_state_push_requested.connect(lambda: undo_events.append(None))
    tool.signals.stroke_completed.connect(lambda: completed_events.append(None))
    start_point = QPoint(5, 5)
    press_event = _MouseEventStub(start_point)
    tool.mousePressEvent(press_event)
    assert press_event.accepted
    move_point = QPoint(8, 8)
    move_event = _MouseEventStub(move_point)
    tool.mouseMoveEvent(move_event)
    assert move_event.accepted
    release_event = _MouseEventStub(move_point)
    tool.mouseReleaseEvent(release_event)
    assert release_event.accepted
    assert strokes == [
        (start_point, start_point, True),
        (start_point, move_point, True),
    ]
    assert len(undo_events) == 1
    assert len(completed_events) == 1
    assert tool.last_paint_anchor_point is not None
    assert tool.last_paint_anchor_point.raw == move_point
    assert tool.is_drawing is False


def test_brush_tool_accepts_back_to_back_taps(qapp):
    """Every distinct mouse press starts a paintable stroke immediately."""
    tool = BrushTool()
    tool.activate(
        PaintingInteractionPort(
            panel_to_content_point=lambda point: point,
        )
    )
    strokes: list[tuple[QPoint, QPoint, bool]] = []
    undo_events: list[None] = []
    completed_events: list[None] = []
    tool.signals.stroke_applied.connect(
        lambda segment: _record_segment(strokes, segment)
    )
    tool.signals.undo_state_push_requested.connect(lambda: undo_events.append(None))
    tool.signals.stroke_completed.connect(lambda: completed_events.append(None))
    point = QPoint(6, 6)
    first_press = _MouseEventStub(point)
    tool.mousePressEvent(first_press)
    assert first_press.accepted
    first_release = _MouseEventStub(point)
    tool.mouseReleaseEvent(first_release)
    assert first_release.accepted
    assert len(strokes) == 1
    assert len(undo_events) == 1
    assert len(completed_events) == 1
    second_press = _MouseEventStub(point)
    tool.mousePressEvent(second_press)
    assert second_press.accepted
    second_release = _MouseEventStub(point)
    tool.mouseReleaseEvent(second_release)
    assert second_release.accepted
    assert len(strokes) == 2
    assert len(undo_events) == 2
    assert len(completed_events) == 2
    third_press = _MouseEventStub(point)
    tool.mousePressEvent(third_press)
    assert third_press.accepted
    third_release = _MouseEventStub(point)
    tool.mouseReleaseEvent(third_release)
    assert third_release.accepted
    assert len(strokes) == 3
    assert len(undo_events) == 3
    assert len(completed_events) == 3


def test_brush_tool_accepts_partial_edge_stroke(qapp):
    tool = BrushTool()
    strokes: list[tuple[QPoint, QPoint, bool]] = []
    tool.signals.stroke_applied.connect(
        lambda segment: _record_segment(strokes, segment)
    )

    def panel_hit(point: QPoint) -> PanelHitTest:
        return PanelHitTest(
            panel_point=point,
            raw_point=QPointF(-1.0, 5.0),
            clamped_point=QPoint(0, 5),
            inside_image=False,
        )

    tool.activate(
        PaintingInteractionPort(
            panel_hit_test=panel_hit,
            is_point_in_widget=lambda _: True,
            get_image_rect=lambda: QRect(QPoint(0, 0), QPoint(9, 9)),
            get_brush_size=lambda: 6,
        )
    )
    press_event = _MouseEventStub(QPoint(0, 5))
    tool.mousePressEvent(press_event)
    assert press_event.accepted
    assert strokes == [(QPoint(-1, 5), QPoint(-1, 5), False)]


def test_brush_tool_ignores_events_outside_widget(qapp):
    tool = BrushTool()
    hit_calls = 0

    def panel_hit(point: QPoint) -> PanelHitTest:
        nonlocal hit_calls
        hit_calls += 1
        return PanelHitTest(
            panel_point=point,
            raw_point=QPointF(point.x(), point.y()),
            clamped_point=point,
            inside_image=True,
        )

    tool.activate(
        PaintingInteractionPort(
            panel_hit_test=panel_hit,
            is_point_in_widget=lambda _: False,
            get_image_rect=lambda: QRect(QPoint(0, 0), QPoint(9, 9)),
        )
    )
    press_event = _MouseEventStub(QPoint(2, 2))
    tool.mousePressEvent(press_event)
    assert not press_event.accepted
    assert hit_calls == 0


def test_brush_tool_denies_mouse_and_pointer_strokes_before_target_work(qapp) -> None:
    """A forbidden operation must emit no mutation or history signal."""
    tool = BrushTool()
    segments: list[BrushStrokeSegment] = []
    undo_events: list[None] = []
    tool.signals.stroke_applied.connect(segments.append)
    tool.signals.undo_state_push_requested.connect(lambda: undo_events.append(None))
    tool.activate(
        PaintingInteractionPort(
            can_paint=lambda: False,
            panel_hit_test_precise=lambda point: PanelHitTest(
                panel_point=point.toPoint(),
                raw_point=QPointF(point),
                clamped_point=point.toPoint(),
                inside_image=True,
            ),
            get_image_rect=lambda: QRect(0, 0, 100, 100),
        )
    )

    mouse_event = _MouseEventStub(QPoint(20, 20))
    tool.mousePressEvent(mouse_event)
    pointer_owned = tool.handle_pointer_sample(
        _pointer_sample(PointerPhase.BEGIN, QPointF(20.0, 20.0), pressure=1.0)
    )

    assert not mouse_event.accepted
    assert not pointer_owned
    assert not segments
    assert not undo_events
