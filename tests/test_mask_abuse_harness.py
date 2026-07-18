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

"""System-level checks for the reusable mounted QPane abuse harness."""

from __future__ import annotations

from itertools import product

import pytest
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QCursor, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from qpane.scene.render_plan import MaskLayerRenderItem
from tests.harness.abuse_model import (
    AbuseAction,
    AbuseReport,
    AbuseViolation,
    HarnessPoint,
    IdleAction,
    PenLeaveAction,
    PointerKind,
    StrokeAction,
    WaitAction,
    action_from_dict,
    action_to_dict,
)
from tests.harness.abuse_runner import MaskAbuseRunner
from tests.harness.input_driver import QtStrokeDriver
from tests.harness.minimizer import minimize_failing_actions
from tests.harness.mounted_qpane import MountedQPaneHarness
from tests.harness.scenarios import (
    deterministic_abuse_actions,
    ordered_device_history_actions,
    overlapping_noop_stroke_actions,
    repeated_touch_mouse_cursor_actions,
    touch_mouse_mask_switch_actions,
)


class _CursorChangeCounter(QObject):
    """Count effective-window cursor mutations during synchronous mouse input."""

    def __init__(self) -> None:
        """Initialize an empty mutation count."""
        super().__init__()
        self.count = 0

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Record cursor changes without consuming the event."""
        del watched
        if event.type() == QEvent.Type.CursorChange:
            self.count += 1
        return False


class _MouseSequenceProbe(QObject):
    """Capture the mouse button lifecycle delivered to a mounted pane."""

    def __init__(self) -> None:
        """Initialize an empty sequence."""
        super().__init__()
        self.samples: list[
            tuple[
                QEvent.Type,
                Qt.MouseButton,
                Qt.MouseButton,
                Qt.MouseEventSource,
            ]
        ] = []

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Record relevant mouse events without consuming them."""
        del watched
        if isinstance(event, QMouseEvent) and event.type() in {
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonRelease,
        }:
            self.samples.append(
                (event.type(), event.button(), event.buttons(), event.source())
            )
        return False


def test_abuse_actions_round_trip_through_replay_payload() -> None:
    """Every deterministic action must retain its meaning in a saved trace."""
    actions = deterministic_abuse_actions()

    restored = tuple(action_from_dict(action_to_dict(action)) for action in actions)

    assert restored == actions


def test_failure_minimizer_removes_irrelevant_actions() -> None:
    """Delta reduction must retain the failure trigger and discard unrelated work."""
    actions = tuple(WaitAction(wait_ms=value) for value in (1, 2, 99, 3, 4))

    def reproduce(candidate: tuple[AbuseAction, ...]) -> AbuseReport:
        failing_index = next(
            (index for index, action in enumerate(candidate) if action.wait_ms == 99),
            None,
        )
        violation = (
            None
            if failing_index is None
            else AbuseViolation(
                action_index=failing_index,
                phase="synthetic",
                message="same defect",
            )
        )
        return AbuseReport(
            seed=7,
            action_count=len(candidate),
            completed_actions=(
                len(candidate) if failing_index is None else failing_index
            ),
            max_feedback_latency_ms=0.0,
            violation=violation,
        )

    minimized, report = minimize_failing_actions(actions, reproduce)

    assert minimized == (WaitAction(wait_ms=99),)
    assert report.violation is not None


def test_mouse_stroke_driver_delivers_complete_physical_sequence(
    qapp: QApplication,
) -> None:
    """The abuse driver must not depend on platform mouse injection state."""
    harness = MountedQPaneHarness(qapp)
    driver = QtStrokeDriver(harness)
    probe = _MouseSequenceProbe()
    stroke = StrokeAction(
        PointerKind.MOUSE,
        points=(HarnessPoint(120, 160), HarnessPoint(180, 160)),
    )
    harness.viewer.installEventFilter(probe)
    try:
        driver.begin(stroke)
        driver.move(stroke, 1)
        driver.end(stroke)

        assert probe.samples == [
            (
                QEvent.Type.MouseButtonPress,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.MouseEventSource.MouseEventNotSynthesized,
            ),
            (
                QEvent.Type.MouseMove,
                Qt.MouseButton.NoButton,
                Qt.MouseButton.LeftButton,
                Qt.MouseEventSource.MouseEventNotSynthesized,
            ),
            (
                QEvent.Type.MouseButtonRelease,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton,
                Qt.MouseEventSource.MouseEventNotSynthesized,
            ),
        ]
        assert harness.wait_for_mask_undo_depth(harness.mask_ids[0], 1)
    finally:
        harness.viewer.removeEventFilter(probe)
        harness.close()


def test_mounted_qpane_survives_deterministic_cross_device_mask_abuse(
    qapp: QApplication,
    tmp_path,
) -> None:
    """A real pane must preserve visible mask history under mixed input abuse."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(2048, 2048),
        widget_size=QSize(500, 500),
        mask_count=2,
    )
    try:
        report = MaskAbuseRunner(
            harness,
            seed=0,
            artifact_directory=tmp_path,
        ).run(deterministic_abuse_actions())
    finally:
        harness.close()

    assert report.succeeded, report.to_dict()


@pytest.mark.parametrize(
    ("first", "second"),
    tuple(product(PointerKind, repeat=2)),
    ids=lambda device: device.value,
)
def test_ordered_device_transitions_preserve_pixels_and_history(
    qapp: QApplication,
    tmp_path,
    first: PointerKind,
    second: PointerKind,
) -> None:
    """Every ordered input pair must survive undo, redo, and history branching."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(2048, 2048),
        widget_size=QSize(500, 500),
        mask_count=1,
    )
    try:
        report = MaskAbuseRunner(
            harness,
            seed=100 + list(product(PointerKind, repeat=2)).index((first, second)),
            artifact_directory=tmp_path / f"{first.value}-{second.value}",
        ).run(ordered_device_history_actions(first, second))
        history = harness.viewer.getMaskUndoState(harness.mask_ids[0])
    finally:
        harness.close()

    assert report.succeeded, report.to_dict()
    assert history is not None
    assert history.undo_depth == 2
    assert history.redo_depth == 0


@pytest.mark.parametrize("image_size", (2048, 4096))
def test_repeated_touch_mouse_cursor_transitions_preserve_history(
    qapp: QApplication,
    tmp_path,
    image_size: int,
) -> None:
    """Repeated touch-to-mouse handoffs must never strand the blank cursor."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(image_size, image_size),
        widget_size=QSize(500, 500),
        mask_count=1,
    )
    try:
        report = MaskAbuseRunner(
            harness,
            seed=200,
            artifact_directory=tmp_path / f"repeated-touch-mouse-{image_size}",
        ).run(repeated_touch_mouse_cursor_actions())
        history = harness.viewer.getMaskUndoState(harness.mask_ids[0])
    finally:
        harness.close()

    assert report.succeeded, report.to_dict()
    assert history is not None
    assert history.undo_depth == 8
    assert history.redo_depth == 0


@pytest.mark.parametrize("_repeat_index", range(5))
def test_demo_order_mouse_touch_passive_mouse_move_restores_brush_cursor(
    qapp: QApplication,
    _repeat_index: int,
) -> None:
    """The reported mouse-paint, touch-paint, mouse-hover order must recover."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(2048, 2048),
        widget_size=QSize(500, 500),
        mask_count=1,
    )
    driver = QtStrokeDriver(harness)
    mouse_stroke = StrokeAction(
        PointerKind.MOUSE,
        points=(HarnessPoint(80, 100), HarnessPoint(180, 100)),
        brush_size=30,
    )
    touch_stroke = StrokeAction(
        PointerKind.TOUCH,
        points=(HarnessPoint(220, 200), HarnessPoint(320, 200)),
        brush_size=30,
    )
    try:
        window = harness.host.windowHandle()
        assert window is not None
        QTest.mouseMove(
            window,
            harness.viewer.mapTo(harness.host, QPoint(80, 100)),
            delay=1,
        )
        harness.drain_events()
        assert window.cursor().shape() != Qt.CursorShape.BlankCursor

        driver.begin(mouse_stroke)
        driver.move(mouse_stroke, 1)
        driver.end(mouse_stroke)
        driver.begin(touch_stroke)
        driver.move(touch_stroke, 1)
        driver.end(touch_stroke)
        cursor_after_touch = harness.viewer.cursor()
        assert cursor_after_touch.shape() != Qt.CursorShape.BlankCursor
        assert not cursor_after_touch.pixmap().isNull()
        effective_cursor_after_touch = window.cursor()
        assert effective_cursor_after_touch.shape() != Qt.CursorShape.BlankCursor
        assert not effective_cursor_after_touch.pixmap().isNull()

        QTest.mouseMove(
            window,
            harness.viewer.mapTo(harness.host, QPoint(360, 260)),
            delay=1,
        )
        harness.drain_events()

        cursor = harness.viewer.cursor()
        assert cursor.shape() != Qt.CursorShape.BlankCursor
        assert not cursor.pixmap().isNull()
        effective_cursor = window.cursor()
        assert effective_cursor.shape() != Qt.CursorShape.BlankCursor
        assert not effective_cursor.pixmap().isNull()
    finally:
        harness.close()


@pytest.mark.parametrize(
    "source",
    (
        Qt.MouseEventSource.MouseEventNotSynthesized,
        Qt.MouseEventSource.MouseEventSynthesizedByQt,
        Qt.MouseEventSource.MouseEventSynthesizedBySystem,
        Qt.MouseEventSource.MouseEventSynthesizedByApplication,
    ),
)
def test_inside_mouse_reconciles_stale_effective_window_cursor_after_touch(
    qapp: QApplication,
    source: Qt.MouseEventSource,
) -> None:
    """Inside motion must repair a blank QWindow despite a brush QWidget cursor."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(2048, 2048),
        widget_size=QSize(500, 500),
        mask_count=1,
    )
    driver = QtStrokeDriver(harness)
    touch_stroke = StrokeAction(
        PointerKind.TOUCH,
        points=(HarnessPoint(220, 200), HarnessPoint(320, 200)),
        brush_size=30,
    )
    try:
        window = harness.host.windowHandle()
        assert window is not None
        cursor_changes = _CursorChangeCounter()
        window.installEventFilter(cursor_changes)
        driver.begin(touch_stroke)
        driver.move(touch_stroke, 1)
        driver.end(touch_stroke)
        assert harness.viewer.cursor().shape() != Qt.CursorShape.BlankCursor

        first_mouse_position = QPointF(340.0, 240.0)
        qapp.sendEvent(
            harness.viewer,
            QMouseEvent(
                QEvent.Type.MouseMove,
                first_mouse_position,
                first_mouse_position,
                QPointF(harness.viewer.mapToGlobal(first_mouse_position.toPoint())),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                Qt.MouseEventSource.MouseEventNotSynthesized,
            ),
        )
        window.setCursor(QCursor(Qt.CursorShape.BlankCursor))
        assert window.cursor().shape() == Qt.CursorShape.BlankCursor
        cursor_changes.count = 0
        position = QPointF(360.0, 260.0)
        qapp.sendEvent(
            harness.viewer,
            QMouseEvent(
                QEvent.Type.MouseMove,
                position,
                position,
                QPointF(harness.viewer.mapToGlobal(position.toPoint())),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                source,
            ),
        )

        assert harness.viewer.cursor().shape() != Qt.CursorShape.BlankCursor
        assert window.cursor().shape() != Qt.CursorShape.BlankCursor
        assert not window.cursor().pixmap().isNull()
        assert cursor_changes.count == 1
        cursor_changes.count = 0
        for offset in range(1, 101):
            moved_position = position + QPointF(float(offset), 0.0)
            qapp.sendEvent(
                harness.viewer,
                QMouseEvent(
                    QEvent.Type.MouseMove,
                    moved_position,
                    moved_position,
                    QPointF(harness.viewer.mapToGlobal(moved_position.toPoint())),
                    Qt.MouseButton.NoButton,
                    Qt.MouseButton.NoButton,
                    Qt.KeyboardModifier.NoModifier,
                    source,
                ),
            )
        assert cursor_changes.count == 0
        harness.drain_events()
        assert window.cursor().shape() != Qt.CursorShape.BlankCursor

        outside_canvas = QWidget(harness.host)
        outside_canvas.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        outside_canvas.setGeometry(0, 0, 40, 40)
        outside_canvas.show()
        outside_canvas.raise_()
        QTest.mouseMove(window, QPoint(20, 20), delay=1)
        harness.drain_events()
        assert window.cursor().shape() == Qt.CursorShape.ArrowCursor

        QTest.mouseMove(window, QPoint(360, 260), delay=1)
        harness.drain_events()
        assert window.cursor().shape() != Qt.CursorShape.BlankCursor
        assert not window.cursor().pixmap().isNull()
    finally:
        harness.close()


@pytest.mark.parametrize("zoom_mode", ("fit", "one-to-one"))
def test_undo_never_presents_a_frame_without_the_retained_mask_pixels(
    qapp: QApplication,
    zoom_mode: str,
) -> None:
    """Undo must atomically replace the visible mask under delayed colorization."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(2048, 2048),
        widget_size=QSize(500, 500),
        mask_count=1,
        brush_size=40,
    )
    driver = QtStrokeDriver(harness)
    retained_stroke = StrokeAction(
        PointerKind.MOUSE,
        points=(HarnessPoint(120, 160), HarnessPoint(180, 160)),
        brush_size=40,
    )
    removed_stroke = StrokeAction(
        PointerKind.MOUSE,
        points=(HarnessPoint(320, 340), HarnessPoint(380, 340)),
        brush_size=40,
    )
    service = harness.viewer.mask_service
    assert service is not None
    controller = service.controller
    mask_id = harness.mask_ids[0]
    previous_prefetch_enabled = service.render_work.enabled
    previous_async_handler = controller.renders._async_handler
    previous_async_threshold = controller.renders._async_threshold_px
    service.setPrefetchEnabled(False)
    retained_point = QPoint(150, 160)
    removed_point = QPoint(350, 340)
    try:
        if zoom_mode == "one-to-one":
            harness.viewer.setZoom1To1(QPoint(250, 250))
            harness.drain_events(wait_ms=10)
        for expected_depth, stroke, probe_point in (
            (1, retained_stroke, retained_point),
            (2, removed_stroke, removed_point),
        ):
            driver.begin(stroke)
            driver.move(stroke, 1)
            driver.end(stroke)
            assert harness.wait_for_mask_undo_depth(
                mask_id,
                expected_depth,
                timeout_ms=5000,
            )
            tint = harness.wait_for_mask_tint(probe_point, timeout_ms=5000)
            assert tint.latency_ms is not None
            harness.drain_events(wait_ms=5)

        before = harness.capture()
        assert harness.is_mask_tint(before.pixelColor(retained_point))
        assert harness.is_mask_tint(before.pixelColor(removed_point))

        controller.renders.cancel_async(mask_id)
        controller.renders.set_async_handler(
            lambda _mask_id, _layer: True,
            threshold_px=1,
        )

        assert harness.viewer.undoMaskEdit()
        harness.viewer.repaint()

        renderer = harness.viewer.view().presenter.renderer
        plan = renderer.get_current_render_plan()
        buffer = renderer.get_base_buffer()
        assert plan is not None
        assert buffer is not None
        margin = renderer._BUFFER_OVERSCAN_PHYSICAL_PX
        retained_color = buffer.pixelColor(
            retained_point.x() + margin,
            retained_point.y() + margin,
        )
        removed_color = buffer.pixelColor(
            removed_point.x() + margin,
            removed_point.y() + margin,
        )

        assert any(isinstance(item, MaskLayerRenderItem) for item in plan.render_items)
        assert harness.is_mask_tint(retained_color)
        assert not harness.is_mask_tint(removed_color)
    finally:
        controller.renders.cancel_async(mask_id)
        controller.renders.set_async_handler(
            previous_async_handler,
            threshold_px=previous_async_threshold,
        )
        service.setPrefetchEnabled(previous_prefetch_enabled)
        harness.close()


def test_touch_mouse_cursor_survives_mask_switches(qapp, tmp_path) -> None:
    """Cursor handoff and independent history must survive active-mask changes."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(4096, 4096),
        widget_size=QSize(500, 500),
        mask_count=2,
    )
    try:
        report = MaskAbuseRunner(
            harness,
            seed=201,
            artifact_directory=tmp_path / "touch-mouse-mask-switch",
        ).run(touch_mouse_mask_switch_actions())
        histories = tuple(
            harness.viewer.getMaskUndoState(mask_id) for mask_id in harness.mask_ids
        )
    finally:
        harness.close()

    assert report.succeeded, report.to_dict()
    assert all(history is not None for history in histories)
    assert all(history.undo_depth == 2 for history in histories if history is not None)
    assert all(history.redo_depth == 0 for history in histories if history is not None)


def test_overlapping_cross_device_noops_preserve_render_and_history(
    qapp,
    tmp_path,
) -> None:
    """Covered mouse and pen strokes must not flash or create no-op history."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(4096, 4096),
        widget_size=QSize(500, 500),
        mask_count=1,
    )
    try:
        report = MaskAbuseRunner(
            harness,
            seed=20260723,
            artifact_directory=tmp_path / "overlapping-noops",
        ).run(overlapping_noop_stroke_actions())
        history = harness.viewer.getMaskUndoState(harness.mask_ids[0])
    finally:
        harness.close()

    assert report.succeeded, report.to_dict()
    assert history is not None
    assert history.undo_depth == 1
    assert history.redo_depth == 0


def test_mounted_qpane_preserves_small_brush_centerlines(qapp, tmp_path) -> None:
    """Near-native zoom must retain small mouse, touch, and pen stroke interiors."""
    actions = (
        StrokeAction(
            PointerKind.MOUSE,
            points=(HarnessPoint(60, 100), HarnessPoint(440, 100)),
            brush_size=12,
        ),
        StrokeAction(
            PointerKind.TOUCH,
            points=(
                HarnessPoint(250, 60),
                HarnessPoint(250, 180),
                HarnessPoint(250, 320),
                HarnessPoint(250, 440),
            ),
            brush_size=16,
            step_delay_ms=2,
        ),
        StrokeAction(
            PointerKind.PEN,
            points=(
                HarnessPoint(80, 420),
                HarnessPoint(200, 300),
                HarnessPoint(320, 180),
                HarnessPoint(420, 80),
            ),
            brush_size=24,
            pressure=0.35,
        ),
        PenLeaveAction(),
    )
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(500, 500),
        widget_size=QSize(500, 500),
        mask_count=2,
    )
    try:
        report = MaskAbuseRunner(
            harness,
            seed=1,
            artifact_directory=tmp_path,
        ).run(actions)
    finally:
        harness.close()

    assert report.succeeded, report.to_dict()


def test_mounted_qpane_idle_baselines_use_durable_stroke_pixels(
    qapp,
    tmp_path,
) -> None:
    """Idle checks must begin after provisional pixels become durable pixels."""
    actions = (
        StrokeAction(
            PointerKind.TOUCH,
            points=(
                HarnessPoint(100, 330),
                HarnessPoint(180, 350),
                HarnessPoint(260, 330),
                HarnessPoint(340, 350),
                HarnessPoint(420, 330),
            ),
            brush_size=104,
        ),
        IdleAction(wait_ms=15),
    )
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(4096, 4096),
        widget_size=QSize(500, 500),
        mask_count=1,
    )
    try:
        report = MaskAbuseRunner(
            harness,
            seed=5006,
            artifact_directory=tmp_path,
        ).run(actions)
    finally:
        harness.close()

    assert report.succeeded, report.to_dict()
