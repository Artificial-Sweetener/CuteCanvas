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
"""Mounted adversarial proof for affine layer-transform interactions."""

from __future__ import annotations

import math
import statistics

import numpy as np
import pytest
from cutecanvas import EditorIntent, LayerPolicy
from cutecanvas.editor.transform_interaction import TransformBoxPresentation
from PySide6.QtCore import QLineF, QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QTransform
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qpane.raster.image_conversion import qimage_to_numpy_argb32

from tests.harness.mounted_qpane import MountedQPaneHarness
from tests.harness.timing import (
    INTERACTIVE_PERFORMANCE,
    absolute_latency_assertions_are_isolated,
    interaction_clock,
)

pytestmark = INTERACTIVE_PERFORMANCE

_MEDIAN_UPDATE_BUDGET_MS = 16.0
_ISOLATED_OUTLIER_BUDGET_MS = 100.0


def test_affine_layer_move_survives_hostile_updates_space_pan_and_replay(
    qapp: QApplication,
) -> None:
    """Affine previews must stay exact, cached, bounded, responsive, and repairable."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(3440, 1440),
        widget_size=QSize(1360, 760),
        mask_count=1,
        cache_budget_mb=96,
    )
    viewer = harness.viewer
    info = viewer.listMasksForComposition()[0]
    mask_id = harness.mask_ids[0]
    try:
        assert info.scene_id is not None
        assert info.layer_id is not None
        viewer.setLayerInteractionPolicy(
            info.scene_id,
            info.layer_id,
            LayerPolicy(
                selectable=True,
                movable=True,
                pixel_editable=True,
            ),
        )
        viewer.setSelectedLayer(info.scene_id, info.layer_id)
        assert viewer.selectedLayer().layer_id == info.layer_id
        layer = viewer.mask_service.assets.get_layer(mask_id)
        assert layer is not None

        def paint_asymmetric_mask(pixels: np.ndarray, _image: QImage) -> None:
            """Create opaque hit coverage with holes and non-symmetric edges."""
            pixels.fill(0)
            pixels[420:980, 760:1760] = 255
            pixels[250:650, 1120:1480] = 255
            pixels[560:760, 1050:1300] = 0

        layer.coverage.raster.mutate(paint_asymmetric_mask)
        viewer.invalidateActiveMaskCache()
        viewer.markDirty()
        viewer.update()
        assert harness.wait_for_mask_render_idle()
        affine = QTransform(0.28, 0.06, -0.04, 0.25, 400.0, 180.0)
        assert viewer.setLayerTransform(info.scene_id, info.layer_id, affine)
        assert harness.wait_for_mask_render_idle()
        viewer.clearPixelSelection()
        viewer.setControlMode(viewer.CONTROL_MODE_MOVE)
        harness.drain_events()
        render_cache = viewer.mask_service.controller._renders
        cache_before = render_cache.snapshot_metrics()
        origin = viewer.view().layer_source_to_panel_point(
            info.scene_id,
            info.layer_id,
            QPointF(900.0, 500.0),
        )
        assert origin is not None

        QTest.mousePress(viewer, Qt.LeftButton, Qt.NoModifier, origin.toPoint())
        harness.drain_events()
        latencies = _drive_hostile_updates(harness, origin.toPoint(), start_index=0)
        preview = viewer.view().current_scene_descriptor()
        assert preview is not None
        preview_transform = next(
            item.transform for item in preview.layers if item.layer_id == info.layer_id
        )
        assert preview_transform is not None
        assert (
            preview_transform.m11,
            preview_transform.m12,
            preview_transform.m21,
            preview_transform.m22,
        ) == (0.28, 0.06, -0.04, 0.25)

        QTest.keyPress(viewer, Qt.Key_Space)
        harness.drain_events()
        suspended = viewer.view().current_scene_descriptor()
        assert suspended is not None
        assert (
            next(
                item.transform
                for item in suspended.layers
                if item.layer_id == info.layer_id
            )
            == preview_transform
        )
        assert viewer.layerTransform(info.scene_id, info.layer_id) == affine
        QTest.keyRelease(viewer, Qt.Key_Space)
        QTest.mouseRelease(viewer, Qt.LeftButton, Qt.NoModifier, origin.toPoint())
        harness.drain_events()

        resumed_origin = viewer.view().layer_source_to_panel_point(
            info.scene_id,
            info.layer_id,
            QPointF(900.0, 500.0),
        )
        assert resumed_origin is not None
        QTest.mousePress(
            viewer,
            Qt.LeftButton,
            Qt.NoModifier,
            resumed_origin.toPoint(),
        )
        harness.drain_events()
        latencies.extend(
            _drive_hostile_updates(
                harness,
                resumed_origin.toPoint(),
                start_index=120,
            )
        )

        renderer = viewer.view().presenter.renderer
        incremental = renderer.get_base_buffer()
        assert incremental is not None
        incremental_pixels = qimage_to_numpy_argb32(incremental.copy())
        viewer.markDirty()
        viewer.update()
        harness.drain_events()
        repaired = renderer.get_base_buffer()
        assert repaired is not None
        np.testing.assert_array_equal(
            incremental_pixels,
            qimage_to_numpy_argb32(repaired.copy()),
        )

        final_pointer = _update_point(resumed_origin.toPoint(), 239)
        QTest.mouseRelease(
            viewer,
            Qt.LeftButton,
            Qt.NoModifier,
            final_pointer,
        )
        harness.drain_events()
        committed = viewer.layerTransform(info.scene_id, info.layer_id)
        assert committed is not None
        assert committed != affine
        assert (committed.m11(), committed.m12(), committed.m21(), committed.m22()) == (
            affine.m11(),
            affine.m12(),
            affine.m21(),
            affine.m22(),
        )
        assert viewer.undoSceneEdit()
        assert viewer.layerTransform(info.scene_id, info.layer_id) == affine
        assert viewer.redoSceneEdit()
        assert viewer.layerTransform(info.scene_id, info.layer_id) == committed
        cache_after = render_cache.snapshot_metrics()
        assert cache_after.misses == cache_before.misses
        assert cache_after.entry_count == cache_before.entry_count
        assert cache_after.cache_bytes == cache_before.cache_bytes
        assert statistics.median(latencies) < _MEDIAN_UPDATE_BUDGET_MS
        if absolute_latency_assertions_are_isolated():
            assert max(latencies) < _ISOLATED_OUTLIER_BUDGET_MS
    finally:
        harness.close()


def test_selected_rgba_free_transform_is_live_lossless_atomic_and_fast(
    qapp: QApplication,
) -> None:
    """Selected pixels must transform without per-sample resampling or stale frames."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(400, 400),
        widget_size=QSize(400, 400),
        mask_count=1,
        cache_budget_mb=96,
    )
    viewer = harness.viewer
    try:
        raster = QImage(400, 400, QImage.Format_ARGB32_Premultiplied)
        raster.fill(Qt.transparent)
        painter = QPainter(raster)
        painter.fillRect(QRect(100, 100, 40, 40), QColor(230, 40, 70, 255))
        painter.end()
        layer_id = viewer.addEditableRasterLayer(
            raster,
            label="Transform target",
            interaction=LayerPolicy(
                selectable=True,
                movable=True,
                pixel_editable=True,
            ),
        )
        scene = viewer.currentScene()
        assert scene is not None and layer_id is not None
        assert viewer.setSelectedLayer(scene.scene_id, layer_id)
        selection = QImage(40, 40, QImage.Format_Grayscale8)
        selection.fill(255)
        assert viewer.setPixelSelection(selection, QRect(100, 100, 40, 40))
        original = viewer.editableRasterLayerImage(scene.scene_id, layer_id)
        assert original is not None
        viewer.setControlMode(viewer.CONTROL_MODE_TRANSFORM)
        harness.drain_events()
        box = viewer.sceneLayerTransformInteraction().presentation()
        assert box is not None
        start = next(
            point for handle, point in box.handles if handle.value == "bottom-right"
        ).toPoint()
        finish = start + QPoint(80, 80)

        QTest.mousePress(viewer, Qt.LeftButton, Qt.NoModifier, start)
        latencies: list[float] = []
        for index in range(120):
            amount = (index * 29) % 81
            point = start + QPoint(amount, amount)
            started = interaction_clock()
            QTest.mouseMove(viewer, point, delay=0)
            harness.drain_events()
            latencies.append((interaction_clock() - started) * 1000.0)
        QTest.mouseMove(viewer, finish, delay=0)
        harness.drain_events()
        preview = viewer._selected_pixel_movement.raster_preview
        assert preview is not None
        assert preview.fragment_transform.m11 == pytest.approx(3.0, abs=0.04)
        assert viewer.editableRasterLayerImage(scene.scene_id, layer_id) == original

        renderer = viewer.view().presenter.renderer
        incremental = renderer.get_base_buffer()
        assert incremental is not None
        incremental_pixels = qimage_to_numpy_argb32(incremental.copy())
        viewer.markDirty()
        viewer.update()
        harness.drain_events()
        repaired = renderer.get_base_buffer()
        assert repaired is not None
        np.testing.assert_array_equal(
            incremental_pixels,
            qimage_to_numpy_argb32(repaired.copy()),
        )

        QTest.mouseRelease(viewer, Qt.LeftButton, Qt.NoModifier, finish)
        harness.drain_events()
        before_space = viewer._selected_pixel_movement.raster_preview
        QTest.keyPress(viewer, Qt.Key_Space)
        harness.drain_events()
        QTest.keyRelease(viewer, Qt.Key_Space)
        harness.drain_events()
        assert viewer._selected_pixel_movement.raster_preview == before_space

        QTest.keyClick(viewer, Qt.Key_Return)
        harness.drain_events()
        committed = viewer.editableRasterLayerImage(scene.scene_id, layer_id)
        assert committed is not None and committed != original
        assert viewer.floatingPixelEditState() is None
        assert committed.pixelColor(215, 215).alpha() > 0
        assert viewer.undoSceneEdit()
        assert viewer.editableRasterLayerImage(scene.scene_id, layer_id) == original
        assert viewer.redoSceneEdit()
        assert viewer.editableRasterLayerImage(scene.scene_id, layer_id) == committed
        assert statistics.median(latencies) < _MEDIAN_UPDATE_BUDGET_MS
        if absolute_latency_assertions_are_isolated():
            assert max(latencies) < _ISOLATED_OUTLIER_BUDGET_MS
    finally:
        harness.close()


def test_whole_layer_transform_is_cumulative_suspendable_atomic_and_fast(
    qapp: QApplication,
) -> None:
    """Eight-point layer transforms must retain one cheap preview until resolution."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(3440, 1440),
        widget_size=QSize(1360, 760),
        mask_count=1,
        cache_budget_mb=96,
    )
    viewer = harness.viewer
    info = viewer.listMasksForComposition()[0]
    mask_id = harness.mask_ids[0]
    try:
        assert info.scene_id is not None and info.layer_id is not None
        viewer.setLayerInteractionPolicy(
            info.scene_id,
            info.layer_id,
            LayerPolicy(
                selectable=True,
                movable=True,
                pixel_editable=True,
            ),
        )
        viewer.setSelectedLayer(info.scene_id, info.layer_id)
        assert viewer.selectedLayer().layer_id == info.layer_id
        layer = viewer.mask_service.assets.get_layer(mask_id)
        assert layer is not None

        def paint_tight_content(pixels: np.ndarray, _image: QImage) -> None:
            """Leave enough transparent padding to expose content-tight handles."""
            pixels.fill(0)
            pixels[400:960, 900:1900] = 255
            pixels[540:740, 1250:1500] = 0

        layer.coverage.raster.mutate(paint_tight_content)
        viewer.invalidateActiveMaskCache()
        viewer.markDirty()
        viewer.update()
        assert harness.wait_for_mask_render_idle()
        original = QTransform(0.28, 0.04, -0.03, 0.27, 310.0, 155.0)
        assert viewer.setLayerTransform(info.scene_id, info.layer_id, original)
        assert harness.wait_for_mask_render_idle()
        viewer.clearPixelSelection()
        viewer.setControlMode(viewer.CONTROL_MODE_TRANSFORM)
        harness.drain_events()
        interaction = viewer.sceneLayerTransformInteraction()
        box = interaction.presentation()
        assert box is not None
        assert len(box.handles) == 8
        expected_top_left = viewer.view().layer_source_to_panel_point(
            info.scene_id,
            info.layer_id,
            QPointF(900.0, 400.0),
        )
        assert expected_top_left is not None
        top_left = dict(box.handles)[
            next(handle for handle, _point in box.handles if handle.value == "top-left")
        ]
        assert QLineF(top_left, expected_top_left).length() < 1.5
        cache = viewer.mask_service.controller._renders
        cache_before = cache.snapshot_metrics()
        start = next(
            point for handle, point in box.handles if handle.value == "bottom-right"
        ).toPoint()

        QTest.mousePress(viewer, Qt.LeftButton, Qt.NoModifier, start)
        latencies: list[float] = []
        for index in range(160):
            amount = (index * 31) % 121
            point = start + QPoint(amount, round(amount * 0.55))
            started = interaction_clock()
            QTest.mouseMove(viewer, point, delay=0)
            harness.drain_events()
            latencies.append((interaction_clock() - started) * 1000.0)
        scaled_finish = start + QPoint(120, 66)
        QTest.mouseMove(viewer, scaled_finish, delay=0)
        QTest.mouseRelease(viewer, Qt.LeftButton, Qt.NoModifier, scaled_finish)
        harness.drain_events()
        scaled_box = interaction.presentation()
        assert scaled_box is not None and scaled_box.unresolved
        assert viewer.layerTransform(info.scene_id, info.layer_id) == original

        rotate_start, rotate_finish = _rotation_drag(scaled_box, 30.0)
        QTest.mousePress(viewer, Qt.LeftButton, Qt.ShiftModifier, rotate_start)
        QTest.mouseMove(viewer, rotate_finish, delay=0)
        harness.drain_events()
        before_space = viewer.view().current_scene_descriptor()
        assert before_space is not None
        preview_transform = next(
            item.transform
            for item in before_space.layers
            if item.layer_id == info.layer_id
        )
        QTest.keyPress(viewer, Qt.Key_Space)
        harness.drain_events()
        during_space = viewer.view().current_scene_descriptor()
        assert during_space is not None
        assert (
            next(
                item.transform
                for item in during_space.layers
                if item.layer_id == info.layer_id
            )
            == preview_transform
        )
        QTest.keyRelease(viewer, Qt.Key_Space)
        QTest.mouseRelease(viewer, Qt.LeftButton, Qt.ShiftModifier, rotate_finish)
        harness.drain_events()
        assert viewer.layerTransform(info.scene_id, info.layer_id) == original

        renderer = viewer.view().presenter.renderer
        incremental = renderer.get_base_buffer()
        assert incremental is not None
        incremental_pixels = qimage_to_numpy_argb32(incremental.copy())
        viewer.markDirty()
        viewer.update()
        harness.drain_events()
        repaired = renderer.get_base_buffer()
        assert repaired is not None
        np.testing.assert_array_equal(
            incremental_pixels,
            qimage_to_numpy_argb32(repaired.copy()),
        )

        QTest.keyClick(viewer, Qt.Key_Return)
        harness.drain_events()
        committed = viewer.layerTransform(info.scene_id, info.layer_id)
        assert committed is not None and committed != original
        assert viewer.undoSceneEdit()
        assert viewer.layerTransform(info.scene_id, info.layer_id) == original
        assert viewer.redoSceneEdit()
        assert viewer.layerTransform(info.scene_id, info.layer_id) == committed

        committed_box = interaction.presentation()
        assert committed_box is not None
        cancel_start = next(
            point
            for handle, point in committed_box.handles
            if handle.value == "top-left"
        ).toPoint()
        cancel_finish = cancel_start - QPoint(40, 25)
        QTest.mousePress(viewer, Qt.LeftButton, Qt.NoModifier, cancel_start)
        QTest.mouseMove(viewer, cancel_finish, delay=0)
        QTest.mouseRelease(viewer, Qt.LeftButton, Qt.NoModifier, cancel_finish)
        QTest.keyClick(viewer, Qt.Key_Escape)
        harness.drain_events()
        assert viewer.layerTransform(info.scene_id, info.layer_id) == committed
        assert not interaction.presentation().unresolved

        cache_after = cache.snapshot_metrics()
        assert cache_after.misses == cache_before.misses
        assert cache_after.entry_count == cache_before.entry_count
        assert cache_after.cache_bytes == cache_before.cache_bytes
        assert statistics.median(latencies) < _MEDIAN_UPDATE_BUDGET_MS
        if absolute_latency_assertions_are_isolated():
            assert max(latencies) < _ISOLATED_OUTLIER_BUDGET_MS
    finally:
        harness.close()


def test_selection_transform_abuse_never_falls_back_to_mask_layer(
    qapp: QApplication,
) -> None:
    """A selection without mask pixels must never create a whole-layer transform."""

    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(256, 256),
        widget_size=QSize(256, 256),
        mask_count=1,
        cache_budget_mb=96,
    )
    viewer = harness.viewer
    mask_id = harness.mask_ids[0]
    info = viewer.listMasksForComposition()[0]
    try:
        assert info.scene_id is not None and info.layer_id is not None
        viewer.setLayerInteractionPolicy(
            info.scene_id,
            info.layer_id,
            LayerPolicy(selectable=True, movable=True, pixel_editable=True),
        )
        viewer.setSelectedLayer(info.scene_id, info.layer_id)
        assert viewer.selectedLayer().layer_id == info.layer_id
        mask = viewer.mask_service.assets.get_layer(mask_id)
        assert mask is not None

        def paint_distant_content(pixels: np.ndarray, _image: QImage) -> None:
            """Keep mask content far from the pixel selection."""

            pixels.fill(0)
            pixels[20:100, 20:100] = 255

        mask.coverage.raster.mutate(paint_distant_content)
        viewer.invalidateActiveMaskCache()
        viewer.markDirty()
        viewer.update()
        assert harness.wait_for_mask_render_idle()
        original_transform = viewer.layerTransform(info.scene_id, info.layer_id)
        selection = QImage(24, 24, QImage.Format_Grayscale8)
        selection.fill(255)
        assert viewer.setPixelSelection(selection, QRect(180, 180, 24, 24))

        state = viewer.editorOperationState(EditorIntent.TRANSFORM)
        assert not state.allowed
        assert state.denial == "no-selected-pixels"
        assert viewer.setControlMode(viewer.CONTROL_MODE_TRANSFORM)
        harness.drain_events()
        assert viewer.sceneLayerTransformInteraction().presentation() is None

        source = viewer.sceneToPanelRect(QRectF(40.0, 40.0, 1.0, 1.0))
        assert source is not None
        origin = source.topLeft().toPoint()
        for index in range(160):
            destination = origin + QPoint(
                ((index * 37) % 91) - 45,
                ((index * 53) % 77) - 38,
            )
            QTest.mousePress(viewer, Qt.LeftButton, Qt.NoModifier, origin)
            QTest.mouseMove(viewer, destination, delay=0)
            QTest.mouseRelease(viewer, Qt.LeftButton, Qt.NoModifier, destination)
        harness.drain_events()

        assert viewer.layerTransform(info.scene_id, info.layer_id) == original_transform
        assert viewer.sceneLayerTransformInteraction().presentation() is None
        viewer.setControlMode(viewer.CONTROL_MODE_DRAW_BRUSH)
        viewer.setBrushSize(8)
        paint_rect = viewer.sceneToPanelRect(QRectF(190.0, 190.0, 1.0, 1.0))
        assert paint_rect is not None
        QTest.mouseClick(viewer, Qt.LeftButton, pos=paint_rect.topLeft().toPoint())
        assert harness.wait_for_mask_render_idle()
        painted = viewer.exportMaskImage(mask_id)
        assert painted is not None
        assert painted.pixelColor(190, 190).value() == 255
        assert viewer.layerTransform(info.scene_id, info.layer_id) == original_transform
    finally:
        harness.close()


def _rotation_drag(
    box: TransformBoxPresentation,
    angle_degrees: float,
) -> tuple[QPoint, QPoint]:
    """Return exterior start/end points rotating around one transform box center."""
    top = next(point for handle, point in box.handles if handle.value == "top")
    radial = top - box.center
    length = math.hypot(radial.x(), radial.y())
    start_vector = QPointF(
        radial.x() / length * (length + 16.0), radial.y() / length * (length + 16.0)
    )
    radians = math.radians(angle_degrees)
    end_vector = QPointF(
        start_vector.x() * math.cos(radians) - start_vector.y() * math.sin(radians),
        start_vector.x() * math.sin(radians) + start_vector.y() * math.cos(radians),
    )
    return (box.center + start_vector).toPoint(), (box.center + end_vector).toPoint()


def _drive_hostile_updates(
    harness: MountedQPaneHarness,
    origin: QPoint,
    *,
    start_index: int,
) -> list[float]:
    """Send reversals and sub-frame direction changes through the real event loop."""
    latencies: list[float] = []
    for index in range(start_index, start_index + 120):
        started = interaction_clock()
        QTest.mouseMove(harness.viewer, _update_point(origin, index), delay=0)
        harness.drain_events()
        latencies.append((interaction_clock() - started) * 1000.0)
    return latencies


def _update_point(origin: QPoint, index: int) -> QPoint:
    """Return a deterministic sawtooth pointer path with frequent reversals."""
    horizontal = (index * 37) % 241 - 120
    vertical = (index * 23) % 121 - 60
    return origin + QPoint(horizontal, vertical)
