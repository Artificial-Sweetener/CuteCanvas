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

"""System-level checks for the reusable mounted CuteCanvas abuse harness."""

from __future__ import annotations

from itertools import product

import numpy as np
import pytest
from cutecanvas import LayerPolicy, RasterExtentPolicy
from cutecanvas_test_support.harness.abuse_model import (
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
from cutecanvas_test_support.harness.abuse_runner import MaskAbuseRunner
from cutecanvas_test_support.harness.timing import INTERACTIVE_PERFORMANCE
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QCursor, QEnterEvent, QImage, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qpane.scene.model import LayerKind

pytestmark = INTERACTIVE_PERFORMANCE
from cutecanvas_test_support.harness.input_driver import QtStrokeDriver
from cutecanvas_test_support.harness.minimizer import minimize_failing_actions
from cutecanvas_test_support.harness.mounted_qpane import MountedQPaneHarness
from cutecanvas_test_support.harness.scenarios import (
    deterministic_abuse_actions,
    ordered_device_history_actions,
    overlapping_noop_stroke_actions,
    repeated_touch_mouse_cursor_actions,
    touch_mouse_mask_switch_actions,
)
from cutecanvas_test_support.harness.timing import (
    absolute_latency_assertions_are_isolated,
    interaction_clock,
    stable_latency_samples,
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
                (
                    event.type(),
                    event.button(),
                    event.buttons(),
                    event.source(),
                )
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


def test_removing_final_mask_disarms_brush_mode_and_cursor(
    qapp: QApplication,
) -> None:
    """A maskless mounted scene must not retain brush interaction feedback."""
    harness = MountedQPaneHarness(qapp, mask_count=1)
    try:
        harness.viewer.refreshCursor()
        assert harness.viewer.getControlMode() == harness.viewer.CONTROL_MODE_DRAW_BRUSH
        assert harness.viewer.cursor().shape() == Qt.CursorShape.BitmapCursor

        assert harness.viewer.removeMaskFromComposition(
            harness.image_id,
            harness.mask_ids[0],
        )
        harness.drain_events(wait_ms=10)

        assert harness.viewer.activeMaskID() is None
        assert harness.viewer.maskIDsForComposition(harness.image_id) == []
        assert harness.viewer.getControlMode() == harness.viewer.CONTROL_MODE_PANZOOM
        assert harness.viewer.cursor().shape() != Qt.CursorShape.BitmapCursor
    finally:
        harness.close()


def test_hidden_raster_never_reappears_during_mask_navigation_abuse(
    qapp: QApplication,
) -> None:
    """Mask-only navigation must retain the canvas and reject stale raster frames."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(1024, 1024),
        widget_size=QSize(500, 500),
        mask_count=1,
        brush_size=48,
    )
    driver = QtStrokeDriver(harness)
    stroke = StrokeAction(
        PointerKind.MOUSE,
        points=(HarnessPoint(220, 250), HarnessPoint(280, 250)),
        brush_size=48,
    )
    try:
        driver.begin(stroke)
        driver.move(stroke, 1)
        driver.end(stroke)
        assert harness.wait_for_mask_undo_depth(harness.mask_ids[0], 1)
        assert harness.wait_for_mask_tint(QPoint(250, 250)).latency_ms is not None

        scene = harness.viewer.currentScene()
        assert scene is not None
        raster = next(
            layer for layer in scene.layers if layer.source_kind == "imported-raster"
        )
        assert harness.viewer.setLayerVisible(
            scene.scene_id,
            raster.layer_id,
            False,
        )
        assert harness.wait_for_mask_render_idle()
        assert harness.wait_for_raster_render_idle()

        for index in range(48):
            zoom = 1.25 + (index % 6) * 0.25
            anchor = QPoint(
                40 + (index * 67) % 420,
                40 + (index * 43) % 420,
            )
            harness.viewer.applyZoom(zoom, anchor=anchor)
            harness.viewer.setPan(
                QPointF(
                    float((index % 9 - 4) * 35),
                    float((index % 7 - 3) * 30),
                )
            )
            harness.drain_events()
            plan = harness.viewer.view().calculateRenderPlan()
            assert plan is not None
            assert all(
                item.descriptor.layer_id != raster.layer_id
                for item in plan.render_items
            )
            if index % 8 == 0:
                assert not harness.capture().isNull()

        renderer = harness.viewer.view().presenter.renderer
        incremental = renderer.get_base_buffer()
        assert incremental is not None
        incremental = incremental.copy()
        renderer.markDirty()
        harness.viewer.update()
        harness.drain_events(wait_ms=10)
        repaired = renderer.get_base_buffer()
        assert repaired is not None
        assert incremental == repaired
    finally:
        harness.close()


def test_moved_default_mask_expands_only_inside_the_canvas_aperture(
    qapp: QApplication,
) -> None:
    """Default masks should retain paint on newly exposed canvas regions."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(400, 400),
        widget_size=QSize(400, 400),
        mask_count=1,
        brush_size=20,
    )
    mask_id = harness.mask_ids[0]
    mask_info = harness.viewer.listMasksForComposition()[0]
    driver = QtStrokeDriver(harness)
    outside_surface = StrokeAction(
        PointerKind.MOUSE,
        points=(HarnessPoint(40, 200), HarnessPoint(60, 200)),
        brush_size=20,
    )
    inside_surface = StrokeAction(
        PointerKind.MOUSE,
        points=(HarnessPoint(140, 200), HarnessPoint(160, 200)),
        brush_size=20,
    )
    try:
        assert mask_info.scene_id is not None
        assert mask_info.layer_id is not None
        assert mask_info.interaction.movable
        assert mask_info.interaction.pixel_editable
        assert harness.viewer.setLayerPlacement(
            mask_info.scene_id,
            mask_info.layer_id,
            QRectF(100.0, 0.0, 400.0, 400.0),
        )
        harness.viewer.setControlMode(harness.viewer.CONTROL_MODE_DRAW_BRUSH)

        driver.begin(outside_surface)
        driver.move(outside_surface, 1)
        driver.end(outside_surface)
        harness.drain_events(wait_ms=10)
        state = harness.viewer.getMaskUndoState(mask_id)
        assert state is not None
        assert state.undo_depth == 1

        driver.begin(inside_surface)
        driver.move(inside_surface, 1)
        driver.end(inside_surface)
        assert harness.wait_for_mask_undo_depth(mask_id, 2)
        exported = harness.viewer.getActiveMaskImage()
        assert exported is not None
        assert exported.size() == QSize(400, 400)
        assert exported.pixelColor(50, 200).red() > 0
        assert exported.pixelColor(150, 200).red() > 0
        assert exported.pixelColor(350, 200).red() == 0
    finally:
        harness.close()


def test_clipped_mask_partial_repaints_preserve_retained_opacity(
    qapp: QApplication,
) -> None:
    """A layer aperture must not broaden the renderer's outer damage clip."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(800, 600),
        widget_size=QSize(800, 600),
        mask_count=1,
        brush_size=40,
    )
    mask_id = harness.mask_ids[0]
    mask_info = harness.viewer.listMasksForComposition()[0]
    driver = QtStrokeDriver(harness)
    retained_point = QPoint(200, 300)
    retained_stroke = StrokeAction(
        PointerKind.MOUSE,
        points=(HarnessPoint(180, 300), HarnessPoint(220, 300)),
        brush_size=40,
    )
    remote_stroke = StrokeAction(
        PointerKind.MOUSE,
        points=tuple(HarnessPoint(x, 300) for x in range(600, 681, 10)),
        brush_size=40,
    )
    try:
        assert mask_info.scene_id is not None
        assert mask_info.layer_id is not None
        assert harness.viewer.setLayerPlacement(
            mask_info.scene_id,
            mask_info.layer_id,
            QRectF(1.0, 0.0, 800.0, 600.0),
        )
        harness.viewer.setControlMode(harness.viewer.CONTROL_MODE_DRAW_BRUSH)

        driver.begin(retained_stroke)
        driver.move(retained_stroke, 1)
        driver.end(retained_stroke)
        assert harness.wait_for_mask_undo_depth(mask_id, 1)
        retained_color = harness.color_at(retained_point)
        assert harness.is_mask_tint(retained_color)

        with harness.observe_presented_frames() as frames:
            driver.begin(remote_stroke)
            for point_index in range(1, len(remote_stroke.points)):
                driver.move(remote_stroke, point_index)
            driver.end(remote_stroke)
            assert harness.wait_for_mask_undo_depth(mask_id, 2)

        assert frames.frames
        assert all(
            frame.color_at(retained_point) == retained_color for frame in frames.frames
        )
    finally:
        harness.close()


@pytest.mark.parametrize(
    "pointer_kind",
    (PointerKind.MOUSE, PointerKind.TOUCH, PointerKind.PEN),
    ids=("mouse", "touch", "pen"),
)
def test_expanding_mask_accepts_real_off_surface_stroke_and_recovers_pixels(
    qapp: QApplication,
    pointer_kind: PointerKind,
) -> None:
    """Every painting modality should grow and retain moved off-canvas content."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(400, 400),
        widget_size=QSize(400, 400),
        mask_count=1,
        brush_size=20,
    )
    mask_id = harness.mask_ids[0]
    mask_info = harness.viewer.listMasksForComposition()[0]
    driver = QtStrokeDriver(harness)
    off_surface = StrokeAction(
        pointer_kind,
        points=(HarnessPoint(40, 200), HarnessPoint(60, 200)),
        brush_size=20,
    )
    try:
        assert mask_info.scene_id is not None
        assert mask_info.layer_id is not None
        assert mask_info.interaction.movable
        assert mask_info.interaction.pixel_editable
        assert harness.viewer.setLayerPlacement(
            mask_info.scene_id,
            mask_info.layer_id,
            QRectF(100.0, 0.0, 400.0, 400.0),
        )
        harness.viewer.setRasterExtentPolicy(
            mask_info.scene_id,
            mask_info.layer_id,
            RasterExtentPolicy.EXPAND_ON_WRITE,
        )
        harness.viewer.setControlMode(harness.viewer.CONTROL_MODE_DRAW_BRUSH)
        structural_scenes: list[object] = []
        harness.viewer.sceneChanged.connect(structural_scenes.append)

        driver.begin(off_surface)
        assert structural_scenes
        preview = harness.wait_for_mask_tint(QPoint(40, 200), timeout_ms=1000)
        assert preview.latency_ms is not None
        driver.move(off_surface, 1)
        driver.end(off_surface)
        assert harness.wait_for_mask_undo_depth(mask_id, 1)

        state = harness.viewer.rasterSurfaceState(
            mask_info.scene_id,
            mask_info.layer_id,
        )
        assert state is not None
        assert state.bounds.x() < 0
        assert state.bounds.width() > 400
        layer = harness.viewer.mask_service.assets.get_layer(mask_id)
        assert layer is not None
        storage_x = -50 - state.bounds.x()
        storage_y = 200 - state.bounds.y()
        assert layer.coverage.raster.snapshot_array()[storage_y, storage_x] > 0
        source_bounds = layer.coverage.source_bounds()
        assert source_bounds is not None

        returned_translation_x = 300.0
        assert harness.viewer.setLayerPlacement(
            mask_info.scene_id,
            mask_info.layer_id,
            QRectF(
                source_bounds.x + returned_translation_x,
                float(source_bounds.y),
                float(source_bounds.width),
                float(source_bounds.height),
            ),
        )
        harness.viewer.markDirty()
        harness.viewer.update()
        visible = harness.wait_for_mask_tint(QPoint(250, 200), timeout_ms=1000)
        assert visible.latency_ms is not None

        assert harness.viewer.undoMaskEdit()
        restored = harness.viewer.rasterSurfaceState(
            mask_info.scene_id,
            mask_info.layer_id,
        )
        assert restored is not None
        assert restored.bounds == QRect(0, 0, 400, 400)
    finally:
        harness.close()


def test_moved_mask_delete_clears_every_selected_visible_pixel(
    qapp: QApplication,
) -> None:
    """A scene selection must clear the matching local pixels after movement."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(400, 400),
        widget_size=QSize(400, 400),
        mask_count=1,
        brush_size=32,
    )
    mask_id = harness.mask_ids[0]
    mask_info = harness.viewer.listMasksForComposition()[0]
    driver = QtStrokeDriver(harness)
    stroke = StrokeAction(
        PointerKind.MOUSE,
        points=(HarnessPoint(40, 200), HarnessPoint(360, 200)),
        brush_size=32,
    )
    try:
        assert mask_info.scene_id is not None
        assert mask_info.layer_id is not None
        harness.viewer.setLayerInteractionPolicy(
            mask_info.scene_id,
            mask_info.layer_id,
            LayerPolicy(
                selectable=True,
                movable=True,
                pixel_editable=True,
            ),
        )
        harness.viewer.setSelectedLayer(
            mask_info.scene_id,
            mask_info.layer_id,
        )
        assert harness.viewer.selectedLayer().layer_id == mask_info.layer_id
        driver.begin(stroke)
        driver.move(stroke, 1)
        driver.end(stroke)
        assert harness.wait_for_mask_undo_depth(mask_id, 1)
        assert harness.wait_for_mask_render_idle()

        harness.viewer.setControlMode(harness.viewer.CONTROL_MODE_MOVE)
        QTest.mousePress(
            harness.viewer,
            Qt.LeftButton,
            Qt.NoModifier,
            QPoint(200, 200),
        )
        QTest.mouseMove(harness.viewer, QPoint(280, 200), delay=1)
        QTest.mouseRelease(
            harness.viewer,
            Qt.LeftButton,
            Qt.NoModifier,
            QPoint(280, 200),
        )
        harness.drain_events()
        moved_scene = harness.viewer.currentScene()
        assert moved_scene is not None
        moved_layer = next(
            candidate
            for candidate in moved_scene.layers
            if candidate.layer_id == mask_info.layer_id
        )
        assert moved_layer.placement == QRectF(80.0, 0.0, 400.0, 400.0)
        layer = harness.viewer.mask_service.assets.get_layer(mask_id)
        assert layer is not None
        before = layer.coverage.snapshot().pixels
        before_storage = layer.coverage.raster.bounds
        assert np.any(before[190:210, 30:200])

        harness.viewer.setControlMode(harness.viewer.CONTROL_MODE_SELECT_RECTANGLE)
        QTest.mousePress(
            harness.viewer,
            Qt.LeftButton,
            Qt.NoModifier,
            QPoint(100, 150),
        )
        QTest.mouseMove(harness.viewer, QPoint(280, 250), delay=1)
        QTest.mouseRelease(
            harness.viewer,
            Qt.LeftButton,
            Qt.NoModifier,
            QPoint(280, 250),
        )
        harness.drain_events()
        selection = harness.viewer.pixelSelectionState()
        assert selection is not None
        assert selection.has_selection

        assert harness.viewer.deleteSelectedPixels()
        assert harness.wait_for_mask_render_idle()
        after = layer.coverage.snapshot().pixels
        assert layer.coverage.raster.bounds == layer.coverage.raster.content_bounds()
        assert layer.coverage.raster.bounds != before_storage

        assert not np.any(after[160:240, 30:190])
        assert (
            harness.wait_for_background(QPoint(130, 200), timeout_ms=1000).latency_ms
            is not None
        )
        assert (
            harness.wait_for_background(QPoint(240, 200), timeout_ms=1000).latency_ms
            is not None
        )
        assert np.array_equal(after[:, :19], before[:, :19])
        assert np.array_equal(after[:, 201:], before[:, 201:])
        retained_point = QPoint(360, 200)
        assert harness.wait_for_mask_tint(retained_point).latency_ms is not None
        with harness.observe_presented_frames() as undo_frames:
            assert harness.viewer.undoSceneEdit()
            assert harness.wait_for_mask_render_idle()
            harness.viewer.repaint()
        assert np.array_equal(layer.coverage.snapshot().pixels, before)
        assert layer.coverage.raster.bounds == layer.coverage.raster.content_bounds()
        assert harness.wait_for_mask_tint(QPoint(130, 200)).latency_ms is not None
        assert all(
            harness.is_mask_tint(frame.color_at(retained_point))
            for frame in undo_frames.frames
        )
        with harness.observe_presented_frames() as redo_frames:
            assert harness.viewer.redoSceneEdit()
            assert harness.wait_for_mask_render_idle()
            harness.viewer.repaint()
        assert not np.any(layer.coverage.snapshot().pixels[160:240, 30:190])
        assert layer.coverage.raster.bounds == layer.coverage.raster.content_bounds()
        assert (
            harness.wait_for_background(QPoint(130, 200), timeout_ms=1000).latency_ms
            is not None
        )
        assert all(
            harness.is_mask_tint(frame.color_at(retained_point))
            for frame in redo_frames.frames
        )
    finally:
        harness.close()


def test_4096_moved_mask_delete_stays_within_interaction_budget(
    qapp: QApplication,
) -> None:
    """Large transformed deletion must remain synchronous only for bounded work."""
    size = 4096
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(size, size),
        widget_size=QSize(500, 500),
        mask_count=1,
    )
    mask_id = harness.mask_ids[0]
    info = harness.viewer.listMasksForComposition()[0]
    try:
        assert info.scene_id is not None
        assert info.layer_id is not None
        harness.viewer.setLayerInteractionPolicy(
            info.scene_id,
            info.layer_id,
            LayerPolicy(
                selectable=True,
                movable=True,
                pixel_editable=True,
            ),
        )
        harness.viewer.setSelectedLayer(info.scene_id, info.layer_id)
        assert harness.viewer.selectedLayer().layer_id == info.layer_id
        assert harness.viewer.setLayerPlacement(
            info.scene_id,
            info.layer_id,
            QRectF(512.0, 0.0, float(size), float(size)),
        )
        layer = harness.viewer.mask_service.assets.get_layer(mask_id)
        assert layer is not None
        layer.coverage.raster.fill(255)
        harness.viewer.invalidateActiveMaskCache()
        harness.viewer.markDirty()
        harness.viewer.update()
        selected_panel = harness.viewer.activeMaskLayerCoordinates().source_to_panel(
            QPoint(600, 1200)
        )
        retained_panel = harness.viewer.activeMaskLayerCoordinates().source_to_panel(
            QPoint(1800, 1200)
        )
        assert selected_panel is not None
        assert retained_panel is not None
        selected_panel = QPoint(round(selected_panel.x()), round(selected_panel.y()))
        retained_panel = QPoint(round(retained_panel.x()), round(retained_panel.y()))
        assert (
            harness.wait_for_mask_tint(selected_panel, timeout_ms=5000).latency_ms
            is not None
        )
        assert (
            harness.wait_for_mask_tint(retained_panel, timeout_ms=5000).latency_ms
            is not None
        )
        selection = QImage(1024, 1024, QImage.Format_Grayscale8)
        selection.fill(255)
        assert harness.viewer.setPixelSelection(
            selection,
            QRect(1024, 1024, 1024, 1024),
        )

        latencies_ms: list[float] = []
        for _cycle in range(8):
            started = interaction_clock()
            assert harness.viewer.deleteSelectedPixels()
            latencies_ms.append((interaction_clock() - started) * 1000.0)
            assert layer.coverage.raster.storage_value(600, 1200) == 0
            started = interaction_clock()
            assert harness.viewer.undoSceneEdit()
            latencies_ms.append((interaction_clock() - started) * 1000.0)
            assert layer.coverage.raster.storage_value(600, 1200) == 255
        assert harness.viewer.deleteSelectedPixels()

        if absolute_latency_assertions_are_isolated():
            assert max(latencies_ms) < 100.0
        pixels = layer.coverage.raster.snapshot_array()
        assert not np.any(pixels[1024:2048, 512:1536])
        assert np.all(pixels[1024:2048, :511] == 255)
        assert np.all(pixels[1024:2048, 1537:] == 255)
        assert harness.wait_for_mask_render_idle(timeout_ms=5000)
        assert (
            harness.wait_for_background(selected_panel, timeout_ms=5000).latency_ms
            is not None
        )
        assert (
            harness.wait_for_mask_tint(retained_panel, timeout_ms=5000).latency_ms
            is not None
        )
    finally:
        harness.close()


def test_selection_clear_clips_to_compact_mask_content_and_remains_undoable(
    qapp: QApplication,
) -> None:
    """Selection clearing must not require tight mask storage to cover selection."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(400, 400),
        widget_size=QSize(500, 500),
        mask_count=1,
    )
    mask_id = harness.mask_ids[0]
    mask_info = harness.viewer.listMasksForComposition()[0]
    try:
        assert mask_info.scene_id is not None
        assert mask_info.layer_id is not None
        harness.viewer.setRasterExtentPolicy(
            mask_info.scene_id,
            mask_info.layer_id,
            RasterExtentPolicy.EXPAND_ON_WRITE,
        )
        layer = harness.viewer.mask_service.assets.get_layer(mask_id)
        assert layer is not None
        assert layer.coverage.raster.extent_policy is RasterExtentPolicy.EXPAND_ON_WRITE
        assert layer.coverage.compact_raster_storage()
        assert layer.coverage.raster.is_null()

        harness.viewer.setControlMode(harness.viewer.CONTROL_MODE_DRAW_BRUSH)
        QTest.mouseClick(
            harness.viewer,
            Qt.LeftButton,
            Qt.NoModifier,
            QPoint(250, 250),
        )
        assert harness.wait_for_mask_render_idle()
        authored_bounds = layer.coverage.authored_bounds
        content_bounds = layer.coverage.content_bounds()
        assert content_bounds is not None
        assert content_bounds != authored_bounds

        assert harness.viewer.selectAllPixels()
        QTest.keyClick(harness.viewer, Qt.Key.Key_Delete)
        assert layer.coverage.content_bounds() is None
        assert harness.viewer.undoSceneEdit()
        assert layer.coverage.content_bounds() == content_bounds
        assert harness.viewer.deleteSelectedPixels()
        assert layer.coverage.content_bounds() is None
        assert harness.viewer.undoSceneEdit()
        assert layer.coverage.content_bounds() == content_bounds
        assert harness.viewer.redoSceneEdit()
        assert layer.coverage.content_bounds() is None
    finally:
        harness.close()


def test_delete_and_history_follow_expanded_negative_mask_bounds(
    qapp: QApplication,
) -> None:
    """Selection edits must refresh the correct storage after left-edge growth."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(400, 400),
        widget_size=QSize(400, 400),
        mask_count=1,
        brush_size=24,
    )
    mask_id = harness.mask_ids[0]
    info = harness.viewer.listMasksForComposition()[0]
    driver = QtStrokeDriver(harness)
    try:
        assert info.scene_id is not None
        assert info.layer_id is not None
        harness.viewer.setLayerInteractionPolicy(
            info.scene_id,
            info.layer_id,
            LayerPolicy(
                selectable=True,
                movable=True,
                pixel_editable=True,
            ),
        )
        harness.viewer.setSelectedLayer(info.scene_id, info.layer_id)
        assert harness.viewer.selectedLayer().layer_id == info.layer_id
        harness.viewer.setRasterExtentPolicy(
            info.scene_id,
            info.layer_id,
            RasterExtentPolicy.EXPAND_ON_WRITE,
        )
        assert harness.viewer.setLayerPlacement(
            info.scene_id,
            info.layer_id,
            QRectF(100.0, 0.0, 400.0, 400.0),
        )
        harness.viewer.setControlMode(harness.viewer.CONTROL_MODE_DRAW_BRUSH)
        for depth, points in enumerate(
            (
                (HarnessPoint(40, 200), HarnessPoint(60, 200)),
                (HarnessPoint(200, 200), HarnessPoint(220, 200)),
            ),
            start=1,
        ):
            stroke = StrokeAction(PointerKind.MOUSE, points, brush_size=24)
            driver.begin(stroke)
            driver.move(stroke, 1)
            driver.end(stroke)
            assert harness.wait_for_mask_undo_depth(mask_id, depth)
        state = harness.viewer.rasterSurfaceState(info.scene_id, info.layer_id)
        assert state is not None
        assert state.bounds.x() < 0
        layer = harness.viewer.mask_service.assets.get_layer(mask_id)
        assert layer is not None
        before_bounds = layer.coverage.content_bounds()
        assert before_bounds is not None
        before = layer.coverage.snapshot(before_bounds)

        selection = QImage(60, 60, QImage.Format_Grayscale8)
        selection.fill(255)
        assert harness.viewer.setPixelSelection(selection, QRect(20, 170, 60, 60))
        assert harness.viewer.deleteSelectedPixels()
        assert harness.wait_for_mask_render_idle()

        assert layer.coverage.coverage_value(-50, 200) == 0
        assert layer.coverage.coverage_value(110, 200) == 255
        assert layer.coverage.raster.bounds == layer.coverage.raster.content_bounds()
        assert (
            harness.wait_for_background(QPoint(50, 200), timeout_ms=1000).latency_ms
            is not None
        )
        assert harness.wait_for_mask_tint(QPoint(210, 200)).latency_ms is not None
        assert harness.viewer.undoSceneEdit()
        restored_bounds = layer.coverage.content_bounds()
        assert restored_bounds is not None
        restored = layer.coverage.snapshot(restored_bounds)
        assert restored.bounds == before.bounds
        assert np.array_equal(restored.pixels, before.pixels)
        assert harness.wait_for_mask_tint(QPoint(50, 200)).latency_ms is not None
    finally:
        harness.close()


def test_expanding_mask_grows_every_edge_through_mounted_brush_input(
    qapp: QApplication,
) -> None:
    """Real brush strokes should expand negative and positive local edges."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(400, 400),
        widget_size=QSize(400, 400),
        mask_count=1,
        brush_size=20,
    )
    mask_id = harness.mask_ids[0]
    mask_info = harness.viewer.listMasksForComposition()[0]
    driver = QtStrokeDriver(harness)
    edge_strokes = (
        (100.0, 0.0, HarnessPoint(40, 200), HarnessPoint(60, 200)),
        (-100.0, 0.0, HarnessPoint(340, 200), HarnessPoint(360, 200)),
        (0.0, 100.0, HarnessPoint(200, 40), HarnessPoint(200, 60)),
        (0.0, -100.0, HarnessPoint(200, 340), HarnessPoint(200, 360)),
    )
    try:
        assert mask_info.scene_id is not None
        assert mask_info.layer_id is not None
        assert mask_info.interaction.movable
        assert mask_info.interaction.pixel_editable
        harness.viewer.setRasterExtentPolicy(
            mask_info.scene_id,
            mask_info.layer_id,
            RasterExtentPolicy.EXPAND_ON_WRITE,
        )
        harness.viewer.setControlMode(harness.viewer.CONTROL_MODE_DRAW_BRUSH)

        for expected_depth, (translate_x, translate_y, start, end) in enumerate(
            edge_strokes,
            start=1,
        ):
            state = harness.viewer.rasterSurfaceState(
                mask_info.scene_id,
                mask_info.layer_id,
            )
            assert state is not None
            layer = harness.viewer.mask_service.assets.get_layer(mask_id)
            assert layer is not None
            source_bounds = layer.coverage.source_bounds()
            assert source_bounds is not None
            assert harness.viewer.setLayerPlacement(
                mask_info.scene_id,
                mask_info.layer_id,
                QRectF(
                    source_bounds.x + translate_x,
                    source_bounds.y + translate_y,
                    source_bounds.width,
                    source_bounds.height,
                ),
            )
            stroke = StrokeAction(
                PointerKind.MOUSE,
                points=(start, end),
                brush_size=20,
            )
            driver.begin(stroke)
            driver.move(stroke, 1)
            driver.end(stroke)
            assert harness.wait_for_mask_undo_depth(mask_id, expected_depth)

        state = harness.viewer.rasterSurfaceState(
            mask_info.scene_id,
            mask_info.layer_id,
        )
        assert state is not None
        assert state.bounds.x() < 0
        assert state.bounds.y() < 0
        assert state.bounds.x() + state.bounds.width() > 400
        assert state.bounds.y() + state.bounds.height() > 400
        layer = harness.viewer.mask_service.assets.get_layer(mask_id)
        assert layer is not None
        pixels = layer.coverage.raster.snapshot_array()
        for local_x, local_y in ((-50, 200), (450, 200), (200, -50), (200, 450)):
            assert (
                pixels[
                    local_y - state.bounds.y(),
                    local_x - state.bounds.x(),
                ]
                > 0
            )
    finally:
        harness.close()


def test_expanding_mask_continuous_edge_stroke_stays_interactive(
    qapp: QApplication,
) -> None:
    """Large expanding masks must not stall or rebuild geometry per sample."""
    size = 4096
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(size, size),
        widget_size=QSize(500, 500),
        mask_count=1,
        brush_size=40,
    )
    mask_info = harness.viewer.listMasksForComposition()[0]
    points = tuple(
        HarnessPoint(round(240 - index * 220 / 63), 250) for index in range(64)
    )
    stroke = StrokeAction(PointerKind.MOUSE, points=points, brush_size=40)
    driver = QtStrokeDriver(harness)
    dispatch_latencies_ms: list[float] = []
    structural_scenes: list[object] = []
    try:
        assert mask_info.scene_id is not None
        assert mask_info.layer_id is not None
        assert mask_info.interaction.movable
        assert mask_info.interaction.pixel_editable
        assert harness.viewer.setLayerPlacement(
            mask_info.scene_id,
            mask_info.layer_id,
            QRectF(size * 0.5, 0.0, size, size),
        )
        harness.viewer.setRasterExtentPolicy(
            mask_info.scene_id,
            mask_info.layer_id,
            RasterExtentPolicy.EXPAND_ON_WRITE,
        )
        harness.viewer.setControlMode(harness.viewer.CONTROL_MODE_DRAW_BRUSH)
        harness.viewer.sceneChanged.connect(structural_scenes.append)

        started = interaction_clock()
        driver.begin(stroke)
        dispatch_latencies_ms.append((interaction_clock() - started) * 1000.0)
        for point_index in range(1, len(points)):
            started = interaction_clock()
            driver.move(stroke, point_index)
            dispatch_latencies_ms.append((interaction_clock() - started) * 1000.0)
        driver.end(stroke)

        latency_samples = stable_latency_samples(dispatch_latencies_ms)
        ordered = sorted(latency_samples)
        percentile_95 = ordered[max(0, round(len(ordered) * 0.95) - 1)]
        assert len(structural_scenes) <= 2
        slow_samples = [
            (index, round(duration, 2))
            for index, duration in enumerate(dispatch_latencies_ms)
            if duration >= 20.0
        ]
        assert percentile_95 < 20.0, slow_samples
        if absolute_latency_assertions_are_isolated():
            assert max(dispatch_latencies_ms) < 35.0, slow_samples
    finally:
        harness.close()


def test_expanding_mask_live_preview_never_flashes_painted_pixels(
    qapp: QApplication,
) -> None:
    """An edge-crossing stroke must retain every already-presented painted pixel."""
    size = 800
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(size, size),
        widget_size=QSize(400, 400),
        mask_count=1,
        brush_size=32,
    )
    mask_info = harness.viewer.listMasksForComposition()[0]
    points = tuple(
        HarnessPoint(round(190 - index * 150 / 31), 200) for index in range(32)
    )
    stroke = StrokeAction(PointerKind.MOUSE, points=points, brush_size=32)
    driver = QtStrokeDriver(harness)
    retained_point = QPoint(150, 200)
    try:
        assert mask_info.scene_id is not None
        assert mask_info.layer_id is not None
        assert mask_info.interaction.movable
        assert mask_info.interaction.pixel_editable
        assert harness.viewer.setLayerPlacement(
            mask_info.scene_id,
            mask_info.layer_id,
            QRectF(size * 0.5, 0.0, size, size),
        )
        harness.viewer.setRasterExtentPolicy(
            mask_info.scene_id,
            mask_info.layer_id,
            RasterExtentPolicy.EXPAND_ON_WRITE,
        )
        harness.viewer.setControlMode(harness.viewer.CONTROL_MODE_DRAW_BRUSH)

        with harness.observe_presented_frames() as frames:
            driver.begin(stroke)
            for point_index in range(1, len(points)):
                driver.move(stroke, point_index)
            driver.end(stroke)
            assert (
                harness.wait_for_mask_tint(
                    QPoint(60, 200),
                    timeout_ms=15_000,
                ).latency_ms
                is not None
            )
            harness.viewer.repaint()

        assert frames.frames
        assert all(frame.mask_layer_count == 1 for frame in frames.frames), tuple(
            (index, frame.mask_layer_ids, frame.mask_item_states)
            for index, frame in enumerate(frames.frames)
            if frame.mask_layer_count != 1
        )
        retained_measurement = harness.wait_for_mask_tint(
            retained_point,
            timeout_ms=1000,
        )
        assert (
            retained_measurement.latency_ms is not None
        ), retained_measurement.color.getRgb()
        first_tinted = next(
            index
            for index, frame in enumerate(frames.frames)
            if harness.is_mask_tint(frame.color_at(retained_point))
        )
        assert all(
            harness.is_mask_tint(frame.color_at(retained_point))
            for frame in frames.frames[first_tinted:]
        )
    finally:
        harness.close()


def test_expanding_mask_structural_undo_never_flashes_retained_pixels(
    qapp: QApplication,
) -> None:
    """Undoing growth must preserve earlier mask pixels in every presented frame."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(400, 400),
        widget_size=QSize(400, 400),
        mask_count=1,
        brush_size=20,
    )
    mask_id = harness.mask_ids[0]
    mask_info = harness.viewer.listMasksForComposition()[0]
    driver = QtStrokeDriver(harness)
    retained_point = QPoint(200, 200)
    expanded_point = QPoint(40, 280)
    retained = StrokeAction(
        PointerKind.MOUSE,
        points=(HarnessPoint(190, 200), HarnessPoint(210, 200)),
        brush_size=20,
    )
    expanded = StrokeAction(
        PointerKind.MOUSE,
        points=(HarnessPoint(40, 280), HarnessPoint(60, 280)),
        brush_size=20,
    )
    try:
        assert mask_info.scene_id is not None
        assert mask_info.layer_id is not None
        assert mask_info.interaction.movable
        assert mask_info.interaction.pixel_editable
        assert harness.viewer.setLayerPlacement(
            mask_info.scene_id,
            mask_info.layer_id,
            QRectF(100.0, 0.0, 400.0, 400.0),
        )
        harness.viewer.setRasterExtentPolicy(
            mask_info.scene_id,
            mask_info.layer_id,
            RasterExtentPolicy.EXPAND_ON_WRITE,
        )
        harness.viewer.setControlMode(harness.viewer.CONTROL_MODE_DRAW_BRUSH)

        for expected_depth, stroke, point in (
            (1, retained, retained_point),
            (2, expanded, expanded_point),
        ):
            driver.begin(stroke)
            driver.move(stroke, 1)
            driver.end(stroke)
            assert harness.wait_for_mask_undo_depth(mask_id, expected_depth)
            assert (
                harness.wait_for_mask_tint(point, timeout_ms=1000).latency_ms
                is not None
            )

        with harness.observe_presented_frames() as frames:
            assert harness.viewer.undoMaskEdit()
            harness.viewer.repaint()
            assert (
                harness.wait_for_background(
                    expanded_point,
                    timeout_ms=15_000,
                ).latency_ms
                is not None
            )
            harness.viewer.repaint()

        assert frames.frames
        assert all(frame.mask_layer_count == 1 for frame in frames.frames)
        assert all(
            harness.is_mask_tint(frame.color_at(retained_point))
            for frame in frames.frames
        )
    finally:
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
        for mask_id in harness.mask_ids:
            layer = harness.viewer.mask_service.assets.get_layer(mask_id)
            assert layer is not None
            assert layer.coverage.compact_raster_storage()
            assert layer.coverage.raster.is_null()
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
    """Canvas entry must repair a stale QWindow cursor after touch input."""
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

        window.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        assert window.cursor().shape() == Qt.CursorShape.ArrowCursor

        qapp.sendEvent(
            harness.viewer,
            QEnterEvent(
                position,
                position,
                QPointF(harness.viewer.mapToGlobal(position.toPoint())),
            ),
        )
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
        margin = renderer.buffer_overscan_physical_px
        retained_color = buffer.pixelColor(
            retained_point.x() + margin,
            retained_point.y() + margin,
        )
        removed_color = buffer.pixelColor(
            removed_point.x() + margin,
            removed_point.y() + margin,
        )

        assert any(item.descriptor.kind is LayerKind.MASK for item in plan.render_items)
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
