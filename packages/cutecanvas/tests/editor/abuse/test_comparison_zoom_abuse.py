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

"""Abuse native comparison through production wheel-zoom presentation."""

from __future__ import annotations

from cutecanvas.document import CanvasDocument
from cutecanvas.presentation import CanvasWorkspace
from cutecanvas_test_support.execution_backend import ControllableExecutionBackend
from cutecanvas_test_support.harness_tools.pan_render_harness import (
    HeadlessPanHarness,
    coordinate_fingerprint_image,
)
from PySide6.QtCore import QElapsedTimer, QEvent, QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent
from PySide6.QtTest import QTest
from qpane.sdk.execution import ExecutionRuntime


def test_comparison_pan_harness_matches_full_redraw_after_long_traversals(
    qapp,
    tmp_path,
) -> None:
    """Reject the first comparison pan frame containing displaced tile regions."""

    primary = coordinate_fingerprint_image(QSize(960, 1344))
    secondary = coordinate_fingerprint_image(QSize(1144, 1608))
    secondary.invertPixels(QImage.InvertMode.InvertRgb)

    def configure_comparison(pane) -> None:
        """Replace the seed scene with one unmistakable two-source comparison."""

        pane.clear()
        primary_entry = pane.addImage(primary, label="primary", select=True)
        secondary_entry = pane.addImage(secondary, label="secondary", select=False)
        pane.setComparisonPair(primary_entry.entry_id, secondary_entry.entry_id)
        pane.setComparisonSplit(0.5)

    harness = HeadlessPanHarness(
        qapp,
        primary,
        viewport_size=QSize(1152, 1104),
        zoom=1.8619791666666665,
        artifact_root=tmp_path,
        configure_qpane=configure_comparison,
    )
    failures = []
    try:
        for drag in _long_pan_drags():
            failures.extend(harness.run(drag, direct_navigation=True))
            if failures:
                break
            QTest.qWait(100)
    finally:
        harness.close()

    assert failures == []


def _long_pan_drags() -> tuple[tuple[QPointF, ...], ...]:
    """Return each released drag from the accepted GUI reproduction."""

    drags: list[tuple[QPointF, ...]] = []
    current = QPointF(-148.5625, 167.211957)
    for delta in (
        QPointF(420.0, -280.0),
        QPointF(420.0, -280.0),
        QPointF(420.0, -280.0),
        QPointF(-560.0, 360.0),
        QPointF(-560.0, 360.0),
        QPointF(-560.0, 360.0),
        QPointF(-560.0, 360.0),
        QPointF(480.0, -320.0),
        QPointF(480.0, -320.0),
    ):
        start = QPointF(current)
        samples: list[QPointF] = []
        for step in range(1, 13):
            current = start + delta * (step / 12.0)
            samples.append(QPointF(current))
        drags.append(tuple(samples))
    return tuple(drags)


def test_wheel_zoom_never_settles_displaced_comparison_tiles(qapp) -> None:
    """Require burst wheel zoom to settle to a canonical comparison frame."""

    primary = _coordinate_pattern(QSize(960, 1344), salt=17)
    secondary = _coordinate_pattern(QSize(1144, 1608), salt=193)
    document = CanvasDocument()
    primary_id = document.create_composition_from_image(primary)
    secondary_id = document.create_composition_from_image(secondary)
    workspace = CanvasWorkspace(document=document, features=())
    try:
        workspace.resize(1152, 1104)
        workspace.setComparisonPresentation(
            primary_id,
            secondary_id,
            split_position=0.5,
        )
        workspace.show()
        qapp.processEvents()
        pane = workspace.currentCanvas()
        assert pane is not None
        pane.applySettings(
            smooth_zoom_enabled=True,
            smooth_zoom_duration_ms=180,
            smooth_zoom_burst_duration_ms=80,
        )

        anchor = QPointF(pane.width() * 0.72, pane.height() * 0.38)
        for _step in range(12):
            _send_zoom_in(pane, anchor)
            QTest.qWait(20)
        QTest.qWait(300)
        pan_before_drag = pane.currentPan()
        for delta in (
            QPoint(420, -280),
            QPoint(420, -280),
            QPoint(420, -280),
            QPoint(-560, 360),
            QPoint(-560, 360),
            QPoint(-560, 360),
            QPoint(-560, 360),
            QPoint(480, -320),
            QPoint(480, -320),
        ):
            _drag_pan(
                qapp,
                pane,
                QPoint(pane.width() * 3 // 4, pane.height() // 2),
                delta,
            )
            QTest.qWait(100)
        assert pane.currentPan() != pan_before_drag
        QTest.qWait(1_000)
        _wait_for_complete_tiles(qapp, pane)

        retained = pane.grab().toImage()
        renderer = pane._rendering.presenter.renderer
        renderer.markDirty()
        pane.update()
        qapp.processEvents()
        canonical = pane.grab().toImage()
        _assert_flat_landmarks_match(retained, canonical, pane=pane)
    finally:
        workspace.close()
        document.close()
        qapp.processEvents()


def test_each_zoomed_tile_arrival_matches_a_clean_comparison_frame(qapp) -> None:
    """Reject every partial tile patch that differs from canonical composition."""

    primary = _coordinate_pattern(QSize(960, 1344), salt=17)
    secondary = _coordinate_pattern(QSize(1144, 1608), salt=193)
    document = CanvasDocument()
    primary_id = document.create_composition_from_image(primary)
    secondary_id = document.create_composition_from_image(secondary)
    backend = ControllableExecutionBackend()
    runtime = ExecutionRuntime(backend)
    workspace = CanvasWorkspace(
        document=document,
        features=(),
        execution_runtime=runtime,
    )
    try:
        workspace.resize(1152, 1104)
        workspace.setComparisonPresentation(
            primary_id,
            secondary_id,
            split_position=0.5,
        )
        workspace.show()
        qapp.processEvents()
        pane = workspace.currentCanvas()
        assert pane is not None
        pane.applySettings(
            smooth_zoom_enabled=True,
            smooth_zoom_duration_ms=180,
            smooth_zoom_burst_duration_ms=80,
        )
        anchor = QPointF(pane.width() * 0.72, pane.height() * 0.38)
        for _step in range(6):
            _send_zoom_in(pane, anchor)
            QTest.qWait(220)
            _assert_retained_surface_matches_forced_render(pane)

        completed_tiles = 0
        while tile_jobs := tuple(
            job
            for job in backend.pending_jobs()
            if job.operation == "render.tile.visible"
        ):
            backend.run_job(tile_jobs[-1])
            qapp.processEvents()
            _assert_retained_surface_matches_forced_render(pane)
            completed_tiles += 1
        assert completed_tiles >= 2
    finally:
        workspace.close()
        runtime.shutdown(wait=False)
        document.close()
        qapp.processEvents()


def _send_zoom_in(pane, anchor: QPointF) -> None:
    """Deliver one wheel step through the mounted top-level Qt window."""

    window = pane.window()
    window_handle = window.windowHandle()
    assert window_handle is not None
    window_anchor = pane.mapTo(window, anchor.toPoint())
    QTest.wheelEvent(
        window_handle,
        window_anchor,
        QPoint(0, 120),
        QPoint(),
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
    )


def _drag_pan(qapp, pane, start: QPoint, delta: QPoint) -> None:
    """Drag the mounted comparison pane in hostile small steps."""

    def send(
        event_type: QEvent.Type,
        position: QPoint,
        button: Qt.MouseButton,
        buttons: Qt.MouseButton,
    ) -> None:
        """Deliver one production mouse event with explicit held-button state."""

        local = QPointF(position)
        global_position = QPointF(pane.mapToGlobal(position))
        qapp.sendEvent(
            pane,
            QMouseEvent(
                event_type,
                local,
                global_position,
                button,
                buttons,
                Qt.KeyboardModifier.NoModifier,
            ),
        )

    send(
        QEvent.Type.MouseButtonPress,
        start,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
    )
    for step in range(1, 13):
        position = start + QPoint(
            delta.x() * step // 12,
            delta.y() * step // 12,
        )
        send(
            QEvent.Type.MouseMove,
            position,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
        )
        QTest.qWait(10)
        pane.grab()
    send(
        QEvent.Type.MouseButtonRelease,
        start + delta,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
    )


def _coordinate_pattern(size: QSize, *, salt: int) -> QImage:
    """Return unique normalized cells that expose any displaced tile."""

    image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    columns = 61
    rows = 83
    for y in range(size.height()):
        row = y * rows // size.height()
        for x in range(size.width()):
            column = x * columns // size.width()
            cell = row * columns + column + salt
            red = (cell * 73 + 19) & 0xFF
            green = (cell * 151 + 47) & 0xFF
            blue = (cell * 199 + 83) & 0xFF
            image.setPixel(x, y, 0xFF000000 | red << 16 | green << 8 | blue)
    return image


def _wait_for_complete_tiles(qapp, pane) -> None:
    """Wait until every visible comparison tile has arrived."""

    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < 5_000:
        qapp.processEvents()
        plan = pane.calculateRenderPlan()
        assert plan is not None
        if all(_item_tiles_complete(item) for item in plan.render_items):
            return
    raise AssertionError("comparison tiles did not settle within 5 seconds")


def _item_tiles_complete(item) -> bool:
    """Return whether one render item owns every visible tile."""

    visible_range = item.visible_tile_range
    if visible_range is None:
        return True
    start_row, end_row, start_column, end_column = visible_range
    expected = (end_row - start_row + 1) * (end_column - start_column + 1)
    return len(item.tiles_to_draw) == expected


def _assert_retained_surface_matches_forced_render(pane) -> None:
    """Compare retained pixels with a same-state canonical full render."""

    retained = pane.grab().toImage()
    pane._rendering.presenter.renderer.markDirty()
    pane.repaint()
    forced = pane.grab().toImage()
    _assert_flat_landmarks_match(retained, forced, pane=pane)


def _assert_flat_landmarks_match(
    actual: QImage,
    expected: QImage,
    *,
    pane,
) -> None:
    """Require equal flat source landmarks while ignoring filtered boundaries."""

    assert actual.size() == expected.size()
    mismatches: list[tuple[int, int, str, str]] = []
    for y in range(9, actual.height() - 9, 11):
        for x in range(9, actual.width() - 9, 13):
            expected_color = expected.pixelColor(x, y)
            if any(
                _channel_error(
                    expected.pixelColor(x + dx, y + dy),
                    expected_color,
                )
                > 2
                for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 3))
            ):
                continue
            actual_color = actual.pixelColor(x, y)
            if _channel_error(actual_color, expected_color) > 48:
                mismatches.append((x, y, expected_color.name(), actual_color.name()))
    assert not mismatches, {
        "count": len(mismatches),
        "bounds": (
            min(value[0] for value in mismatches),
            min(value[1] for value in mismatches),
            max(value[0] for value in mismatches),
            max(value[1] for value in mismatches),
        ),
        "first": mismatches[:12],
        "zoom": pane.currentZoom(),
        "pan": pane.currentPan(),
    }


def _channel_error(actual: QColor, expected: QColor) -> int:
    """Return the greatest RGB channel difference."""

    return max(
        abs(actual.red() - expected.red()),
        abs(actual.green() - expected.green()),
        abs(actual.blue() - expected.blue()),
    )
