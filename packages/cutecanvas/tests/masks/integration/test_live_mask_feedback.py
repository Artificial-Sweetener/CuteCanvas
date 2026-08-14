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

"""Mounted-widget probes for visible mask feedback before stroke release."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QImage,
    QInputDevice,
    QMouseEvent,
    QPainter,
    QPointingDevice,
    QTabletEvent,
)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cutecanvas import CuteCanvas
from cutecanvas_test_support.harness import MountedQPaneHarness
from cutecanvas_test_support.harness.abuse_model import (
    HarnessPoint,
    PointerKind,
    StrokeAction,
)
from cutecanvas_test_support.harness.input_driver import QtStrokeDriver
from cutecanvas_test_support.harness.timing import (
    INTERACTIVE_PERFORMANCE,
    interaction_clock,
)
from qpane.scene.render_plan import SampledLayerRenderItem
from qpane.sdk.raster import qimage_to_numpy_const_view_bgra32

_ZOOMED_OUT_4K_AVERAGE_POINTER_BUDGET_MS = 10.0
_ZOOMED_OUT_4K_COLD_CONTACT_BUDGET_MS = 25.0


def _fractional_zoom_source() -> QImage:
    """Return a detailed source that exposes transient sampling changes."""
    image = QImage(4096, 4096, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(22, 34, 58))
    painter = QPainter(image)
    try:
        for offset in range(1792, 2305, 4):
            color = QColor(
                70 + offset % 157,
                35 + (offset * 3) % 181,
                55 + (offset * 7) % 173,
            )
            painter.fillRect(offset, 1792, 2, 513, color)
            painter.fillRect(1792, offset, 513, 2, color)
    finally:
        painter.end()
    return image


class MountedMaskFeedbackProbe(MountedQPaneHarness):
    """Mount a real offscreen CuteCanvas and sample its composited widget pixels."""

    def __init__(
        self,
        qapp: QApplication,
        *,
        image_size: QSize | None = None,
    ) -> None:
        """Create a shown brush-mode pane with one publicly created mask."""
        super().__init__(qapp, image_size=image_size)
        self._qapp = qapp

    def wait_for_visible_paint(self, point: QPoint, *, timeout_ms: int = 150):
        """Measure time until the mask tint reaches ``point`` on the widget."""
        return self.wait_for_mask_tint(point, timeout_ms=timeout_ms)

    def wait_for_white(self, point: QPoint, *, timeout_ms: int = 150):
        """Measure time until provisional paint is absent at ``point``."""
        return self.wait_for_background(point, timeout_ms=timeout_ms)

    _is_mask_tint = staticmethod(MountedQPaneHarness.is_mask_tint)


@pytest.mark.parametrize("image_size", [QSize(400, 400), QSize(1600, 1600)])
def test_mouse_contact_presents_mask_before_release(
    qapp: QApplication,
    image_size: QSize,
) -> None:
    """Mouse contact must tint mounted pixels before its button is released."""
    probe = MountedMaskFeedbackProbe(qapp, image_size=image_size)
    point = QPoint(200, 200)
    try:
        QTest.mousePress(
            probe.viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            point,
        )

        measurement = probe.wait_for_visible_paint(point)

        assert measurement.latency_ms is not None, measurement.color.getRgb()
        QTest.mouseRelease(
            probe.viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            point,
        )
    finally:
        probe.close()


@pytest.mark.parametrize("image_size", [QSize(400, 400), QSize(1600, 1600)])
def test_touch_contact_presents_mask_before_release(
    qapp: QApplication,
    image_size: QSize,
) -> None:
    """A stationary painting finger must tint mounted pixels while held down."""
    probe = MountedMaskFeedbackProbe(qapp, image_size=image_size)
    point = QPoint(200, 200)
    device = QTest.createTouchDevice()
    try:
        QTest.touchEvent(probe.viewer, device).press(0, point, probe.viewer).commit()

        measurement = probe.wait_for_visible_paint(point)

        assert measurement.latency_ms is not None, measurement.color.getRgb()
        QTest.touchEvent(probe.viewer, device).release(0, point, probe.viewer).commit()
    finally:
        probe.close()


def test_pen_contact_presents_mask_before_release(qapp: QApplication) -> None:
    """Synthetic stylus pressure must tint mounted pixels before pen-up."""
    probe = MountedMaskFeedbackProbe(qapp)
    point = QPointF(200.0, 200.0)
    device = QPointingDevice(
        "Synthetic pen",
        501,
        QInputDevice.DeviceType.Stylus,
        QPointingDevice.PointerType.Pen,
        QInputDevice.Capability.Position
        | QInputDevice.Capability.Pressure
        | QInputDevice.Capability.Hover,
        1,
        1,
    )
    try:
        press = _tablet_event(
            device,
            QEvent.Type.TabletPress,
            point,
            pressure=0.75,
            buttons=Qt.MouseButton.LeftButton,
        )
        qapp.sendEvent(probe.viewer, press)

        measurement = probe.wait_for_visible_paint(point.toPoint())

        assert press.isAccepted()
        assert measurement.latency_ms is not None, measurement.color.getRgb()
        qapp.sendEvent(
            probe.viewer,
            _tablet_event(
                device,
                QEvent.Type.TabletRelease,
                point,
                pressure=0.0,
                buttons=Qt.MouseButton.NoButton,
            ),
        )
    finally:
        probe.close()


def test_rapid_second_mouse_drag_presents_new_pixels_before_release(
    qapp: QApplication,
) -> None:
    """A rapid nearby second press must not suppress its subsequent drag."""
    probe = MountedMaskFeedbackProbe(qapp)
    start = QPoint(140, 200)
    destination = QPoint(260, 200)
    try:
        QTest.mouseClick(
            probe.viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            start,
        )
        QTest.mousePress(
            probe.viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            start,
        )
        QTest.mouseMove(probe.viewer, destination, delay=1)

        measurement = probe.wait_for_visible_paint(destination)

        assert measurement.latency_ms is not None, measurement.color.getRgb()
        QTest.mouseRelease(
            probe.viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            destination,
        )
    finally:
        probe.close()


def test_held_mouse_drag_presents_filled_continuous_stroke_before_release(
    qapp: QApplication,
) -> None:
    """A moving preview must remain filled across its accumulated interior."""
    probe = MountedMaskFeedbackProbe(qapp)
    probe.viewer.setBrushSize(40)
    start = QPoint(100, 200)
    end = QPoint(300, 200)
    try:
        QTest.mousePress(
            probe.viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            start,
        )
        for x_position in range(120, end.x() + 1, 20):
            QTest.mouseMove(probe.viewer, QPoint(x_position, 200), delay=1)
            qapp.processEvents()

        missing_pixels = [
            (x_position, y_position)
            for x_position in range(110, 281, 10)
            for y_position in (190, 200, 210)
            if not probe._is_mask_tint(
                probe.viewer.grab().toImage().pixelColor(x_position, y_position)
            )
        ]

        assert missing_pixels == []
        QTest.mouseRelease(
            probe.viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            end,
        )
    finally:
        probe.close()


@pytest.mark.parametrize("device", tuple(PointerKind))
def test_decimated_drag_preview_presents_each_move_without_forced_grab(
    qapp: QApplication,
    device: PointerKind,
) -> None:
    """Low-zoom preview frames must show every held-contact move naturally."""
    probe = MountedQPaneHarness(
        qapp,
        image_size=QSize(4096, 4096),
        widget_size=QSize(320, 500),
        brush_size=30,
    )
    action = StrokeAction(
        device=device,
        points=tuple(
            HarnessPoint(x_position, 250) for x_position in range(48, 273, 32)
        ),
        brush_size=30,
        step_delay_ms=1,
    )
    driver = QtStrokeDriver(probe)
    pressed = False
    try:
        assert probe.viewer.currentZoom() == pytest.approx(0.078125)
        with probe.observe_presented_frames() as frame_probe:
            for point_index, harness_point in enumerate(action.points):
                point = harness_point.to_qpoint()
                frame_count = len(frame_probe.frames)
                if point_index == 0:
                    driver.begin(action)
                    pressed = True
                else:
                    driver.move(action, point_index)
                QTest.qWait(20)
                qapp.processEvents()

                presented = frame_probe.frames[frame_count:]
                assert presented, f"move {point_index} did not present a frame"
                frame = presented[-1]
                assert any(
                    probe.is_mask_tint(frame.color_at(point + QPoint(dx, dy)))
                    for dy in range(-4, 5)
                    for dx in range(-4, 5)
                ), f"move {point_index} presented no mask feedback"
    finally:
        if pressed:
            driver.end(action)
        probe.close()


def test_cold_decimated_preview_accumulates_without_internal_patch_edges(
    qapp: QApplication,
) -> None:
    """A held first stroke must remain cumulative and visually seamless."""
    probe = MountedQPaneHarness(
        qapp,
        image_size=QSize(4096, 4096),
        widget_size=QSize(320, 500),
        brush_size=320,
    )
    points = tuple(QPoint(x_position, 250) for x_position in range(56, 281, 16))
    pressed = False
    try:
        mask_id = probe.mask_ids[0]
        probe.viewer.mask_service.controller.renders.invalidate(mask_id)
        started = interaction_clock()
        QTest.mousePress(
            probe.viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            points[0],
        )
        qapp.processEvents()
        contact_ms = (interaction_clock() - started) * 1000.0
        pressed = True
        assert contact_ms < _ZOOMED_OUT_4K_COLD_CONTACT_BUDGET_MS
        for point_index, point in enumerate(points[1:], start=1):
            QTest.mouseMove(probe.viewer, point, delay=0)
            qapp.processEvents()
            frame = probe.capture()
            assert all(
                probe.is_mask_tint(frame.pixelColor(previous))
                for previous in points[: point_index + 1]
            ), f"preview lost accumulated coverage after move {point_index}"

        live = probe.capture()
        center_colors = tuple(
            live.pixelColor(x_position, 250).getRgb()
            for x_position in range(points[0].x() + 8, points[-1].x() - 7)
        )
        assert len(set(center_colors)) == 1

        QTest.mouseRelease(
            probe.viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            points[-1],
        )
        pressed = False
        assert probe.wait_for_mask_undo_depth(mask_id, 1)
        assert probe.wait_for_mask_render_idle()
        assert probe.wait_for_raster_render_idle()
        settled = probe.capture()
        assert all(probe.is_mask_tint(settled.pixelColor(point)) for point in points)
        settled_colors = tuple(
            settled.pixelColor(x_position, 250).getRgb()
            for x_position in range(points[0].x() + 8, points[-1].x() - 7)
        )
        assert len(set(settled_colors)) == 1
    finally:
        if pressed:
            QTest.mouseRelease(
                probe.viewer,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                points[-1],
            )
        probe.close()


@pytest.mark.parametrize(
    ("zoom", "with_retained_coverage"),
    [
        (1.95, False),
        (2.01, False),
        (2.125, False),
        (3.9, False),
        (4.1, False),
        (1.95, True),
    ],
)
def test_fractional_zoom_mask_pixels_do_not_change_when_stroke_settles(
    qapp: QApplication,
    zoom: float,
    with_retained_coverage: bool,
) -> None:
    """Durable raster-backed presentation must match the held mask exactly."""
    probe = MountedQPaneHarness(
        qapp,
        source_image=_fractional_zoom_source(),
        widget_size=QSize(800, 600),
        brush_size=80,
    )
    start = QPoint(300, 300)
    end = QPoint(500, 300)
    expected_undo_depth = 1
    pressed = False
    try:
        if with_retained_coverage:
            assert probe.viewer.editor.coverage.rectangle(
                QRectF(1800.0, 1800.0, 256.0, 256.0)
            )
            expected_undo_depth = 2
            assert probe.wait_for_mask_render_idle()
            assert probe.wait_for_render_refinement_idle()
        probe.viewer.setZoom1To1()
        probe.viewer.view().viewport.applyZoom(zoom)
        probe.drain_events()
        assert probe.viewer.currentZoom() == pytest.approx(zoom)

        QTest.mousePress(
            probe.viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            start,
        )
        pressed = True
        for x_position in range(start.x() + 10, end.x() + 1, 10):
            QTest.mouseMove(probe.viewer, QPoint(x_position, end.y()), delay=0)
            qapp.processEvents()
        probe.drain_events()
        held = probe.capture()
        current_buffer = probe.viewer.view().presenter.renderer.get_base_buffer()
        assert current_buffer is not None
        held_buffer = current_buffer.copy()

        with probe.observe_presented_frames() as presented:
            QTest.mouseRelease(
                probe.viewer,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                end,
            )
            pressed = False
            assert probe.wait_for_mask_undo_depth(
                probe.mask_ids[0],
                expected_undo_depth,
            )
            assert probe.wait_for_mask_render_idle()
            assert probe.wait_for_raster_render_idle()
            assert probe.wait_for_render_refinement_idle()
        settled = probe.capture()
        render_plan = probe.viewer.view().calculateRenderPlan()

        assert render_plan is not None
        mask_items = tuple(
            item
            for item in render_plan.render_items
            if getattr(item.descriptor.source, "resource_id", None) == probe.mask_ids[0]
        )
        assert len(mask_items) == 1
        assert isinstance(mask_items[0], SampledLayerRenderItem)
        held_pixels, _held_backing = qimage_to_numpy_const_view_bgra32(held)
        settled_pixels, _settled_backing = qimage_to_numpy_const_view_bgra32(settled)
        changed = np.any(held_pixels != settled_pixels, axis=2)
        assert not np.any(changed), (
            int(np.count_nonzero(changed)),
            int(
                np.max(
                    np.abs(
                        held_pixels.astype(np.int16) - settled_pixels.astype(np.int16)
                    )
                )
            ),
            tuple(frame.mask_item_states for frame in presented.frames),
        )
        transition_deltas = []
        held_buffer_pixels, _held_buffer_backing = qimage_to_numpy_const_view_bgra32(
            held_buffer
        )
        for frame in presented.frames:
            frame_pixels, _frame_backing = qimage_to_numpy_const_view_bgra32(
                frame.image
            )
            frame_changed = np.any(frame_pixels != held_buffer_pixels, axis=2)
            transition_deltas.append(
                (
                    int(np.count_nonzero(frame_changed)),
                    int(
                        np.max(
                            np.abs(
                                frame_pixels.astype(np.int16)
                                - held_buffer_pixels.astype(np.int16)
                            )
                        )
                    ),
                    frame.mask_item_states,
                )
            )
        assert all(
            changed_count == 0 for changed_count, _delta, _state in transition_deltas
        ), transition_deltas
    finally:
        if pressed:
            QTest.mouseRelease(
                probe.viewer,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                end,
            )
        probe.close()


def test_intersecting_mask_previews_preserve_both_layers_while_held(
    qapp: QApplication,
) -> None:
    """A second cold preview must not corrupt its own or another mask's pixels."""
    probe = MountedQPaneHarness(
        qapp,
        image_size=QSize(4096, 4096),
        widget_size=QSize(320, 500),
        mask_count=2,
        brush_size=384,
    )
    horizontal = tuple(QPoint(x_position, 250) for x_position in range(64, 273, 16))
    vertical = tuple(QPoint(168, y_position) for y_position in range(146, 355, 16))
    second_pressed = False
    try:
        QTest.mousePress(
            probe.viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            horizontal[0],
        )
        for point in horizontal[1:]:
            QTest.mouseMove(probe.viewer, point, delay=0)
            qapp.processEvents()
        QTest.mouseRelease(
            probe.viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            horizontal[-1],
        )
        assert probe.wait_for_mask_undo_depth(probe.mask_ids[0], 1)
        before_second = probe.capture()
        preserved_points = (QPoint(80, 250), QPoint(256, 250))
        preserved_colors = tuple(
            before_second.pixelColor(point).getRgb() for point in preserved_points
        )

        second_id = probe.activate_mask(1)
        probe.viewer.mask_service.controller.renders.invalidate(second_id)
        QTest.mousePress(
            probe.viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            vertical[0],
        )
        second_pressed = True
        for point_index, point in enumerate(vertical[1:], start=1):
            QTest.mouseMove(probe.viewer, point, delay=0)
            qapp.processEvents()
            frame = probe.capture()
            assert all(
                probe.is_mask_tint(frame.pixelColor(previous))
                for previous in vertical[: point_index + 1]
            ), f"intersecting preview lost coverage after move {point_index}"

        held = probe.capture()
        assert (
            tuple(held.pixelColor(point).getRgb() for point in preserved_points)
            == preserved_colors
        )
        assert probe.is_mask_tint(held.pixelColor(QPoint(168, 250)))
    finally:
        if second_pressed:
            QTest.mouseRelease(
                probe.viewer,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                vertical[-1],
            )
        probe.close()


def test_settled_mask_tiles_stay_seamless_when_another_mask_is_added(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    """A tiled mask refinement must stay uniform across later layer changes."""
    image_size = QSize(2048, 2048)
    probe = MountedQPaneHarness(
        qapp,
        image_size=image_size,
        widget_size=QSize(800, 600),
    )
    mask_path = tmp_path / "uniform-mask.png"
    uniform_mask = QImage(image_size, QImage.Format.Format_Grayscale8)
    uniform_mask.fill(Qt.GlobalColor.white)
    assert uniform_mask.save(str(mask_path))
    try:
        loaded_mask_id = probe.viewer.loadMaskFromFile(str(mask_path))
        assert loaded_mask_id is not None
        probe.viewer.setZoom1To1()
        probe.viewer.view().viewport.applyZoom(1.37)
        assert probe.wait_for_mask_render_idle()
        assert probe.wait_for_raster_render_idle()
        assert probe.wait_for_render_refinement_idle(), (
            probe.viewer.view().presenter._render_refinement.pending_count,
            tuple(probe.viewer.view().presenter._render_refinement._pending),
            tuple(probe.viewer.view().presenter._render_refinement._deferred),
        )
        render_plan = probe.viewer.view().calculateRenderPlan()
        assert render_plan is not None
        loaded_mask_items = tuple(
            item
            for item in render_plan.render_items
            if isinstance(item, SampledLayerRenderItem)
            and getattr(item.descriptor.source, "resource_id", None) == loaded_mask_id
        )
        assert len(loaded_mask_items) == 1, tuple(
            (
                item.descriptor.source,
                len(item.tiles),
            )
            for item in render_plan.render_items
            if isinstance(item, SampledLayerRenderItem)
        )
        assert len(loaded_mask_items[0].tiles) == 1
        assert probe.viewer.view().presenter._render_tile_cache.entry_count >= 2

        for offset_index in range(12):
            probe.viewer.setPan(
                QPointF(
                    offset_index / 8.0,
                    (offset_index * 3 % 12) / 8.0,
                )
            )
            probe.drain_events()
            swept = probe.capture()
            assert (
                len(
                    {
                        swept.pixelColor(x_position, 300).rgba()
                        for x_position in range(32, 768)
                    }
                )
                == 1
            ), f"vertical mask seam at pan sample {offset_index}"
            assert (
                len(
                    {
                        swept.pixelColor(400, y_position).rgba()
                        for y_position in range(32, 568)
                    }
                )
                == 1
            ), f"horizontal mask seam at pan sample {offset_index}"
        probe.viewer.setPan(QPointF())
        probe.drain_events()
        before = probe.capture()
        horizontal_before = tuple(
            before.pixelColor(x_position, 300).rgba() for x_position in range(32, 768)
        )
        vertical_before = tuple(
            before.pixelColor(400, y_position).rgba() for y_position in range(32, 568)
        )
        assert len(set(horizontal_before)) == 1
        assert len(set(vertical_before)) == 1

        added_mask_id = probe.viewer.createBlankMask(image_size)
        assert added_mask_id is not None
        assert probe.wait_for_mask_render_idle()
        assert probe.wait_for_raster_render_idle()
        after = probe.capture()

        assert (
            tuple(
                after.pixelColor(x_position, 300).rgba()
                for x_position in range(32, 768)
            )
            == horizontal_before
        )
        assert (
            tuple(
                after.pixelColor(400, y_position).rgba()
                for y_position in range(32, 568)
            )
            == vertical_before
        )
    finally:
        probe.close()


def test_mask_stays_visually_stable_during_layer_creation_and_tool_switches(
    qapp: QApplication,
) -> None:
    """Unchanged mask pixels must survive every frame of adjacent UI transitions."""
    image_size = QSize(4096, 4096)
    probe = MountedQPaneHarness(
        qapp,
        image_size=image_size,
        widget_size=QSize(640, 480),
        brush_size=768,
    )
    start = QPoint(120, 240)
    end = QPoint(520, 240)
    retained_point = QPoint(320, 240)
    painted_mask_id = probe.mask_ids[0]
    pressed = False
    try:
        QTest.mousePress(
            probe.viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            start,
        )
        pressed = True
        for x_position in range(140, end.x() + 1, 20):
            QTest.mouseMove(probe.viewer, QPoint(x_position, 240), delay=0)
            qapp.processEvents()
        held_color = probe.capture().pixelColor(retained_point)
        assert probe.is_mask_tint(held_color)

        with probe.observe_presented_frames() as presented:
            QTest.mouseRelease(
                probe.viewer,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                end,
            )
            pressed = False
            for layer_index in range(6):
                added_mask_id = probe.viewer.createBlankMask(image_size)
                assert added_mask_id is not None
                assert probe.viewer.setMaskProperties(
                    added_mask_id,
                    color=QColor.fromHsv(layer_index * 45, 200, 255),
                )
                assert probe.viewer.setActiveMaskID(added_mask_id)
                for mode in (
                    probe.viewer.CONTROL_MODE_MOVE,
                    probe.viewer.CONTROL_MODE_PANZOOM,
                    probe.viewer.CONTROL_MODE_DRAW_BRUSH,
                ):
                    probe.viewer.setControlMode(mode)
                    qapp.processEvents()
            assert probe.wait_for_mask_render_idle()
            assert probe.wait_for_raster_render_idle()

        assert presented.frames
        unstable = tuple(
            (
                frame_index,
                frame.color_at(retained_point).getRgb(),
                frame.mask_layer_count,
                frame.mask_item_states,
                frame.mask_sample_scales,
            )
            for frame_index, frame in enumerate(presented.frames)
            if frame.color_at(retained_point) != held_color
        )
        assert unstable == ()
        assert probe.wait_for_mask_undo_depth(painted_mask_id, 1)
        painted_layer = probe.viewer.mask_service.assets.get_layer(painted_mask_id)
        assert painted_layer is not None
        assert np.any(painted_layer.coverage.raster.snapshot_array())

        assert probe.viewer.setActiveMaskID(painted_mask_id)
        render_revision = probe.viewer.mask_service.controller.renders.render_revision(
            painted_mask_id
        )
        with probe.observe_presented_frames() as reordered:
            assert probe.viewer.createBlankMask(image_size) is not None
            assert probe.viewer.mask_service.ensureActiveMaskForComposition(
                probe.viewer.currentCompositionID()
            )
            probe.drain_events()
        assert reordered.frames
        assert all(
            frame.color_at(retained_point) == held_color for frame in reordered.frames
        )
        assert (
            probe.viewer.mask_service.controller.renders.render_revision(
                painted_mask_id
            )
            == render_revision
        )
    finally:
        if pressed:
            QTest.mouseRelease(
                probe.viewer,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                end,
            )
        probe.close()


def test_mask_color_change_never_presents_uncovered_pixels(
    qapp: QApplication,
) -> None:
    """Appearance replacement must retain mask coverage in every presented frame."""
    probe = MountedQPaneHarness(
        qapp,
        image_size=QSize(4096, 4096),
        widget_size=QSize(640, 480),
        brush_size=768,
    )
    point = QPoint(320, 240)
    try:
        QTest.mouseClick(
            probe.viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            point,
        )
        assert probe.wait_for_mask_undo_depth(probe.mask_ids[0], 1)
        before = probe.capture().pixelColor(point)
        background = QColor(Qt.GlobalColor.white)
        assert before != background

        with probe.observe_presented_frames() as presented:
            assert probe.viewer.setMaskProperties(
                probe.mask_ids[0],
                color=QColor.fromHsv(120, 220, 255),
            )
            assert probe.wait_for_mask_render_idle()
            assert probe.wait_for_raster_render_idle()
            assert probe.wait_for_render_refinement_idle()

        assert presented.frames
        assert all(frame.color_at(point) != background for frame in presented.frames)
        assert probe.capture().pixelColor(point) != before
    finally:
        probe.close()


def test_mask_selection_and_layer_creation_preserve_composited_colors(
    qapp: QApplication,
) -> None:
    """Selecting or adding masks must not mutate existing presentation order."""
    probe = MountedQPaneHarness(
        qapp,
        image_size=QSize(400, 400),
        widget_size=QSize(400, 400),
        mask_count=2,
    )
    first_mask, second_mask = probe.mask_ids
    try:
        first_layer = probe.viewer.mask_service.assets.get_layer(first_mask)
        second_layer = probe.viewer.mask_service.assets.get_layer(second_mask)
        assert first_layer is not None and second_layer is not None

        def fill_first(pixels: np.ndarray, _image: QImage) -> None:
            """Fill the left three quarters of the first mask."""
            pixels[:, :300] = 255

        def fill_second(pixels: np.ndarray, _image: QImage) -> None:
            """Fill the right three quarters of the second mask."""
            pixels[:, 100:] = 255

        first_layer.coverage.raster.mutate(fill_first)
        second_layer.coverage.raster.mutate(fill_second)
        assert probe.viewer.setMaskProperties(first_mask, color=QColor(255, 40, 40))
        assert probe.viewer.setMaskProperties(second_mask, color=QColor(40, 220, 80))
        probe.viewer.mask_service.invalidateMaskCache(first_mask)
        probe.viewer.mask_service.invalidateMaskCache(second_mask)
        probe.viewer.mask_service.controller.mask_updated.emit(None, QRect())
        probe.viewer.setControlMode(probe.viewer.CONTROL_MODE_PANZOOM)
        assert probe.wait_for_mask_render_idle()
        assert probe.wait_for_render_refinement_idle()
        probe.drain_events()

        sample_points = (QPoint(50, 200), QPoint(200, 200), QPoint(350, 200))
        order_before = tuple(probe.viewer.maskIDsForComposition(probe.image_id))
        colors_before = tuple(
            probe.capture().pixelColor(point).rgba() for point in sample_points
        )

        for mask_id in (second_mask, first_mask, second_mask):
            assert probe.viewer.setActiveMaskID(mask_id)
            probe.drain_events()
            assert (
                tuple(probe.viewer.maskIDsForComposition(probe.image_id))
                == order_before
            )
            assert (
                tuple(
                    probe.capture().pixelColor(point).rgba() for point in sample_points
                )
                == colors_before
            )

        added_mask = probe.viewer.createBlankMask(QSize(400, 400))
        assert added_mask is not None
        assert probe.viewer.setActiveMaskID(added_mask)
        probe.drain_events()
        order_after = tuple(probe.viewer.maskIDsForComposition(probe.image_id))
        assert order_after[:-1] == order_before
        assert (
            tuple(probe.capture().pixelColor(point).rgba() for point in sample_points)
            == colors_before
        )
    finally:
        probe.close()


@INTERACTIVE_PERFORMANCE
def test_zoomed_out_4k_mask_scribble_keeps_pointer_work_bounded(
    qapp: QApplication,
) -> None:
    """A broad live stroke must not scale pointer latency with its prior envelope."""
    probe = MountedQPaneHarness(
        qapp,
        image_size=QSize(3840, 2160),
        widget_size=QSize(1280, 720),
        brush_size=96,
    )
    points = [QPoint(100 + round(index * 1080 / 79), 100) for index in range(80)]
    points.extend(QPoint(1180, 100 + round(index * 520 / 79)) for index in range(1, 80))
    points.extend(
        QPoint(1180 - round(index * 1080 / 79), 620) for index in range(1, 80)
    )
    points.extend(QPoint(100, 620 - round(index * 520 / 79)) for index in range(1, 80))
    pressed = False
    try:
        assert probe.viewer.currentZoom() == pytest.approx(1.0 / 3.0)
        QTest.mousePress(
            probe.viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            points[0],
        )
        pressed = True
        for point in points[1:160]:
            QTest.mouseMove(probe.viewer, point, delay=0)
            qapp.processEvents()

        started = interaction_clock()
        for point in points[160:]:
            QTest.mouseMove(probe.viewer, point, delay=0)
            qapp.processEvents()
        average_ms = (interaction_clock() - started) * 1000.0 / len(points[160:])

        QTest.mouseRelease(
            probe.viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            points[-1],
        )
        pressed = False
        assert probe.wait_for_mask_undo_depth(probe.mask_ids[0], 1)
        frame = probe.capture()
        for point in (points[40], points[120], points[200], points[280]):
            assert probe.is_mask_tint(frame.pixelColor(point))
        assert average_ms < _ZOOMED_OUT_4K_AVERAGE_POINTER_BUDGET_MS
        assert probe.viewer.undoSceneEdit()
        undo_feedback = probe.wait_for_background(points[40], timeout_ms=3000)
        assert undo_feedback.latency_ms is not None
        assert undo_feedback.latency_ms < 150.0
        assert probe.viewer.redoSceneEdit()
        redo_feedback = probe.wait_for_mask_tint(points[40], timeout_ms=3000)
        assert redo_feedback.latency_ms is not None
        assert redo_feedback.latency_ms < 150.0
    finally:
        if pressed:
            QTest.mouseRelease(
                probe.viewer,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                points[-1],
            )
        probe.close()


def test_mouse_brush_cursor_stays_high_contrast_across_input_transitions(
    qapp: QApplication,
) -> None:
    """The mouse brush cursor must remain a visible dual-tone size preview."""
    probe = MountedMaskFeedbackProbe(qapp)
    point = QPoint(180, 200)
    try:
        _assert_high_contrast_brush_cursor(probe.viewer)
        QTest.mouseMove(probe.viewer, point)
        _assert_high_contrast_brush_cursor(probe.viewer)
        QTest.mousePress(
            probe.viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            point,
        )
        QTest.mouseMove(probe.viewer, point + QPoint(30, 0), delay=1)
        _assert_high_contrast_brush_cursor(probe.viewer)
        QTest.mouseRelease(
            probe.viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            point + QPoint(30, 0),
        )
        touch_device = QTest.createTouchDevice()
        QTest.touchEvent(probe.viewer, touch_device).press(
            0, point, probe.viewer
        ).commit()
        QTest.touchEvent(probe.viewer, touch_device).release(
            0, point, probe.viewer
        ).commit()
        mouse_move = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(point),
            QPointF(point),
            QPointF(point),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.MouseEventSource.MouseEventNotSynthesized,
        )
        qapp.sendEvent(probe.viewer, mouse_move)

        _assert_high_contrast_brush_cursor(probe.viewer)
    finally:
        probe.close()


def test_second_touch_rolls_back_provisional_dab_before_navigation(
    qapp: QApplication,
) -> None:
    """Two-finger takeover must remove its provisional dab and navigate cleanly."""
    probe = MountedMaskFeedbackProbe(qapp, image_size=QSize(800, 800))
    probe.viewer.applySettings(touch_inertia_enabled=False)
    probe.viewer.view().viewport.apply_direct_manipulation(1.0, QPointF())
    first = QPoint(160, 200)
    second = QPoint(240, 200)
    device = QTest.createTouchDevice()
    try:
        QTest.touchEvent(probe.viewer, device).press(0, first, probe.viewer).commit()
        assert probe.wait_for_visible_paint(first).latency_ms is not None

        QTest.touchEvent(probe.viewer, device).move(0, first, probe.viewer).press(
            1, second, probe.viewer
        ).commit()

        rollback = probe.wait_for_white(first)
        assert rollback.latency_ms is not None, rollback.color.getRgb()
        QTest.touchEvent(probe.viewer, device).move(
            0, first + QPoint(20, 10), probe.viewer
        ).move(1, second + QPoint(20, 10), probe.viewer).commit()
        probe._qapp.processEvents()
        assert probe.viewer.getPan() != QPointF()
        QTest.touchEvent(probe.viewer, device).release(
            0, first + QPoint(20, 10), probe.viewer
        ).release(1, second + QPoint(20, 10), probe.viewer).commit()
    finally:
        probe.close()


def _tablet_event(
    device: QPointingDevice,
    event_type: QEvent.Type,
    position: QPointF,
    *,
    pressure: float,
    buttons: Qt.MouseButton,
) -> QTabletEvent:
    """Build one pressure-bearing tablet event for the mounted stylus probe."""
    return QTabletEvent(
        event_type,
        device,
        position,
        position,
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


def _assert_high_contrast_brush_cursor(viewer: CuteCanvas) -> None:
    """Assert that ``viewer`` exposes a non-empty cursor with dark and light pixels."""
    cursor_pixmap = viewer.cursor().pixmap()
    assert not cursor_pixmap.isNull()
    cursor_image = cursor_pixmap.toImage()
    opaque_colors = [
        cursor_image.pixelColor(x_position, y_position)
        for y_position in range(cursor_image.height())
        for x_position in range(cursor_image.width())
        if cursor_image.pixelColor(x_position, y_position).alpha() >= 128
    ]
    assert opaque_colors
    assert any(color.value() <= 32 for color in opaque_colors)
    assert any(color.value() >= 223 for color in opaque_colors)
