#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Mounted hostile-scale tests for selection-aware content movement."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from qpane import QPaneLayerInteractionPolicy
from qpane.raster.image_conversion import (
    numpy_to_qimage_grayscale8,
    qimage_to_numpy_argb32,
)

from .harness.mounted_qpane import MountedQPaneHarness
from .harness.timing import (
    absolute_latency_assertions_are_isolated,
    interaction_clock,
)

_INTERACTION_BUDGET_MS = 100.0
_DEMO_SCALE_PREVIEW_BUDGET_MS = 75.0
_INTERACTION_OUTLIER_BUDGET_MS = 125.0


@pytest.mark.parametrize("canvas_size", (4096, 8192))
def test_large_mask_selected_pixel_drag_preview_commit_and_undo_stay_responsive(
    qapp: QApplication,
    canvas_size: int,
) -> None:
    """4K and 8K masks must move bounded selected pixels without full-raster motion work."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(canvas_size, canvas_size),
        widget_size=QSize(512, 512),
        mask_count=1,
    )
    viewer = harness.viewer
    mask_id = harness.mask_ids[0]
    info = viewer.listMasksForImage()[0]
    selection_size = 1024
    selection_origin = canvas_size // 4
    displacement = 1536
    try:
        assert info.scene_id is not None
        assert info.layer_id is not None
        assert viewer.setLayerInteractionPolicy(
            info.scene_id,
            info.layer_id,
            QPaneLayerInteractionPolicy(
                selectable=True,
                movable=True,
                pixel_editable=True,
            ),
        )
        assert viewer.setSelectedLayer(info.scene_id, info.layer_id)
        layer = viewer.mask_service.assets.get_layer(mask_id)
        assert layer is not None
        layer.surface.fill(255)
        viewer.invalidateActiveMaskCache()
        viewer.markDirty()
        viewer.update()
        selection = QImage(
            selection_size,
            selection_size,
            QImage.Format_Grayscale8,
        )
        selection.fill(255)
        assert viewer.setPixelSelection(
            selection,
            QRect(
                selection_origin,
                selection_origin,
                selection_size,
                selection_size,
            ),
        )
        source_local = QPoint(
            selection_origin + selection_size // 2,
            selection_origin + selection_size // 2,
        )
        destination_local = source_local + QPoint(displacement, 0)
        source_panel = viewer.activeMaskLayerCoordinates().source_to_panel(source_local)
        destination_panel = viewer.activeMaskLayerCoordinates().source_to_panel(
            destination_local
        )
        assert source_panel is not None
        assert destination_panel is not None
        source_point = source_panel.toPoint()
        destination_point = destination_panel.toPoint()
        viewer.setControlMode(viewer.CONTROL_MODE_MOVE)

        latencies_ms: list[float] = []
        for _cycle in range(4):
            QTest.mousePress(viewer, Qt.LeftButton, Qt.NoModifier, source_point)
            assert viewer._selected_pixel_movement.active
            started = interaction_clock()
            QTest.mouseMove(viewer, destination_point, delay=1)
            harness.drain_events()
            latencies_ms.append((interaction_clock() - started) * 1000.0)
            preview = viewer._selected_pixel_movement.raster_preview
            assert preview is not None
            assert preview.delta_x == displacement
            started = interaction_clock()
            QTest.mouseRelease(
                viewer,
                Qt.LeftButton,
                Qt.NoModifier,
                destination_point,
            )
            latencies_ms.append((interaction_clock() - started) * 1000.0)
            assert viewer.floatingPixelEditState() is not None
            started = interaction_clock()
            assert viewer.anchorFloatingPixels()
            latencies_ms.append((interaction_clock() - started) * 1000.0)
            assert (
                layer.surface.storage_value(
                    selection_origin,
                    selection_origin,
                )
                == 0
            )
            assert (
                layer.surface.storage_value(
                    selection_origin + displacement,
                    selection_origin,
                )
                == 255
            )
            started = interaction_clock()
            assert viewer.undoSceneEdit()
            latencies_ms.append((interaction_clock() - started) * 1000.0)
            assert (
                layer.surface.storage_value(
                    selection_origin,
                    selection_origin,
                )
                == 255
            )

        assert max(latencies_ms) < _INTERACTION_BUDGET_MS
    finally:
        harness.close()


def test_demo_scale_fragmented_mask_move_stays_interactive_across_many_updates(
    qapp: QApplication,
) -> None:
    """A painted 1000px selection must preview, commit, and replay without pauses."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(3440, 1440),
        widget_size=QSize(2048, 900),
        mask_count=1,
    )
    viewer = harness.viewer
    info = viewer.listMasksForImage()[0]
    mask_id = harness.mask_ids[0]
    try:
        assert info.scene_id is not None
        assert info.layer_id is not None
        assert viewer.setLayerInteractionPolicy(
            info.scene_id,
            info.layer_id,
            QPaneLayerInteractionPolicy(
                selectable=True,
                movable=True,
                pixel_editable=True,
            ),
        )
        assert viewer.setSelectedLayer(info.scene_id, info.layer_id)
        layer = viewer.mask_service.assets.get_layer(mask_id)
        assert layer is not None

        def paint_fragmented_content(
            pixels: np.ndarray,
            _image: QImage,
        ) -> None:
            """Paint alternating bands with substantial transparent selection area."""
            pixels.fill(0)
            for y in range(200, 1200, 40):
                pixels[y : y + 20, 800:1800] = 255

        layer.surface.mutate(paint_fragmented_content)
        viewer.invalidateActiveMaskCache()
        viewer.markDirty()
        viewer.update()
        assert harness.wait_for_mask_render_idle()
        selection = QImage(1000, 1000, QImage.Format_Grayscale8)
        selection.fill(255)
        assert viewer.setPixelSelection(selection, QRect(800, 200, 1000, 1000))
        coordinates = viewer.activeMaskLayerCoordinates()
        source = coordinates.source_to_panel(QPoint(1300, 690))
        assert source is not None
        viewer.setControlMode(viewer.CONTROL_MODE_MOVE)

        started = interaction_clock()
        QTest.mousePress(
            viewer,
            Qt.LeftButton,
            Qt.NoModifier,
            source.toPoint(),
        )
        harness.drain_events()
        begin_ms = (interaction_clock() - started) * 1000.0
        assert viewer._selected_pixel_movement.active

        update_ms: list[float] = []
        destination = source.toPoint()
        for displacement in range(20, 401, 20):
            mapped = coordinates.source_to_panel(QPoint(1300 + displacement, 690))
            assert mapped is not None
            destination = mapped.toPoint()
            started = interaction_clock()
            QTest.mouseMove(viewer, destination, delay=0)
            harness.drain_events()
            update_ms.append((interaction_clock() - started) * 1000.0)
        preview = viewer._selected_pixel_movement.raster_preview
        assert preview is not None
        assert preview.delta_x == 400

        started = interaction_clock()
        QTest.mouseRelease(viewer, Qt.LeftButton, Qt.NoModifier, destination)
        harness.drain_events()
        assert viewer.floatingPixelEditState() is not None
        assert viewer.anchorFloatingPixels()
        commit_ms = (interaction_clock() - started) * 1000.0
        assert not viewer._selected_pixel_movement.active
        assert layer.surface.storage_value(900, 210) == 0
        assert layer.surface.storage_value(1900, 210) == 255
        moved_selection = viewer.pixelSelectionState()
        assert moved_selection is not None
        assert moved_selection.bounds == QRect(1200, 200, 1000, 980)
        assert moved_selection.coverage is not None
        assert moved_selection.coverage.pixelColor(10, 10).red() == 255
        assert moved_selection.coverage.pixelColor(10, 30).red() == 0

        started = interaction_clock()
        assert viewer.undoSceneEdit()
        harness.drain_events()
        undo_ms = (interaction_clock() - started) * 1000.0
        assert layer.surface.storage_value(900, 210) == 255
        restored_selection = viewer.pixelSelectionState()
        assert restored_selection is not None
        assert restored_selection.bounds == QRect(800, 200, 1000, 1000)

        started = interaction_clock()
        assert viewer.redoSceneEdit()
        harness.drain_events()
        redo_ms = (interaction_clock() - started) * 1000.0
        assert layer.surface.storage_value(900, 210) == 0
        assert float(np.median(update_ms)) < _DEMO_SCALE_PREVIEW_BUDGET_MS
        if absolute_latency_assertions_are_isolated():
            assert (
                max(
                    begin_ms,
                    commit_ms,
                    undo_ms,
                    redo_ms,
                    *update_ms,
                )
                < _INTERACTION_OUTLIER_BUDGET_MS
            )
    finally:
        harness.close()


def test_incremental_mask_drags_match_full_redraw_across_preview_and_commits(
    qapp: QApplication,
) -> None:
    """Preview and committed drags must not retain pieces of prior destinations."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(3440, 1440),
        widget_size=QSize(1360, 760),
        mask_count=1,
    )
    viewer = harness.viewer
    info = viewer.listMasksForImage()[0]
    mask_id = harness.mask_ids[0]
    try:
        assert info.scene_id is not None
        assert info.layer_id is not None
        assert viewer.setLayerInteractionPolicy(
            info.scene_id,
            info.layer_id,
            QPaneLayerInteractionPolicy(
                selectable=True,
                movable=True,
                pixel_editable=True,
            ),
        )
        assert viewer.setSelectedLayer(info.scene_id, info.layer_id)
        assert viewer.setLayerPlacement(
            info.scene_id,
            info.layer_id,
            QRectF(120.0, 60.0, 3000.0, 1260.0),
        )
        layer = viewer.mask_service.assets.get_layer(mask_id)
        assert layer is not None

        def paint_mask(pixels: np.ndarray, _image: QImage) -> None:
            """Paint a large asymmetric shape with a crisp right edge."""
            pixels.fill(0)
            pixels[260:1180, 420:1680] = 255
            pixels[120:520, 760:1260] = 255

        layer.surface.mutate(paint_mask)
        original_mask = layer.surface.snapshot_array()
        viewer.invalidateActiveMaskCache()
        viewer.markDirty()
        viewer.update()
        assert harness.wait_for_mask_render_idle()
        assert viewer.selectLayerCoverage(info.scene_id, info.layer_id)
        coordinates = viewer.activeMaskLayerCoordinates()
        source = coordinates.source_to_panel(QPoint(1000, 700))
        assert source is not None
        viewer.setControlMode(viewer.CONTROL_MODE_MOVE)
        QTest.mousePress(viewer, Qt.LeftButton, Qt.NoModifier, source.toPoint())
        harness.drain_events()

        destination = source
        for displacement_x, displacement_y in (
            (1200, -126),
            (300, 137),
            (900, -173),
            (100, 50),
        ):
            destination = coordinates.source_to_panel(
                QPoint(1000 + displacement_x, 700 + displacement_y)
            )
            assert destination is not None
            QTest.mouseMove(viewer, destination.toPoint(), delay=0)
            harness.drain_events()

        renderer = viewer.view().presenter.renderer
        incremental_buffer = renderer.get_base_buffer()
        assert incremental_buffer is not None
        incremental_pixels = qimage_to_numpy_argb32(incremental_buffer.copy())

        viewer.markDirty()
        viewer.update()
        harness.drain_events()
        repaired_buffer = renderer.get_base_buffer()
        assert repaired_buffer is not None
        repaired_pixels = qimage_to_numpy_argb32(repaired_buffer.copy())

        np.testing.assert_array_equal(incremental_pixels, repaired_pixels)

        QTest.mouseRelease(
            viewer,
            Qt.LeftButton,
            Qt.NoModifier,
            destination.toPoint(),
        )
        harness.drain_events()
        assert viewer.floatingPixelEditState() is not None
        current_local = QPoint(1100, 750)
        for target_local in (
            QPoint(1280, 820),
            QPoint(2310, 700),
            QPoint(1470, 730),
        ):
            current_panel = coordinates.source_to_panel(current_local)
            target_panel = coordinates.source_to_panel(target_local)
            assert current_panel is not None
            assert target_panel is not None
            QTest.mousePress(
                viewer,
                Qt.LeftButton,
                Qt.NoModifier,
                current_panel.toPoint(),
            )
            harness.drain_events()
            QTest.mouseMove(viewer, target_panel.toPoint(), delay=0)
            harness.drain_events()
            QTest.mouseRelease(
                viewer,
                Qt.LeftButton,
                Qt.NoModifier,
                target_panel.toPoint(),
            )
            harness.drain_events()
            current_local = target_local

        floating_buffer = renderer.get_base_buffer()
        assert floating_buffer is not None
        floating_pixels = qimage_to_numpy_argb32(floating_buffer.copy())
        viewer.markDirty()
        viewer.update()
        harness.drain_events()
        repaired_floating_buffer = renderer.get_base_buffer()
        assert repaired_floating_buffer is not None
        repaired_floating_pixels = qimage_to_numpy_argb32(
            repaired_floating_buffer.copy()
        )
        np.testing.assert_array_equal(floating_pixels, repaired_floating_pixels)

        assert viewer.anchorFloatingPixels()
        assert harness.wait_for_mask_render_idle()
        harness.drain_events()

        actual_mask = layer.surface.snapshot_array()
        np.testing.assert_array_equal(
            _trim_occupied(actual_mask),
            _trim_occupied(original_mask),
        )

        committed_buffer = renderer.get_base_buffer()
        assert committed_buffer is not None
        committed_pixels = qimage_to_numpy_argb32(committed_buffer.copy())
        np.testing.assert_array_equal(floating_pixels, committed_pixels)
        viewer.markDirty()
        viewer.update()
        harness.drain_events()
        committed_repair = renderer.get_base_buffer()
        assert committed_repair is not None
        committed_repair_pixels = qimage_to_numpy_argb32(committed_repair.copy())
        np.testing.assert_array_equal(committed_pixels, committed_repair_pixels)

        assert viewer.undoSceneEdit()
        assert harness.wait_for_mask_render_idle()
        assert viewer.redoSceneEdit()
        assert harness.wait_for_mask_render_idle()
        replay_source = coordinates.source_to_panel(current_local)
        replay_target = coordinates.source_to_panel(QPoint(1700, 800))
        assert replay_source is not None
        assert replay_target is not None
        QTest.mousePress(
            viewer,
            Qt.LeftButton,
            Qt.NoModifier,
            replay_source.toPoint(),
        )
        harness.drain_events()
        QTest.mouseMove(viewer, replay_target.toPoint(), delay=0)
        harness.drain_events()
        QTest.mouseRelease(
            viewer,
            Qt.LeftButton,
            Qt.NoModifier,
            replay_target.toPoint(),
        )
        harness.drain_events()
        assert viewer.anchorFloatingPixels()
        np.testing.assert_array_equal(
            _trim_occupied(layer.surface.snapshot_array()),
            _trim_occupied(original_mask),
        )
    finally:
        harness.close()


def test_soft_mask_preview_is_pixel_identical_to_transformed_commit(
    qapp: QApplication,
) -> None:
    """Soft scalar coverage must survive transformed floating presentation exactly."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(800, 600),
        widget_size=QSize(920, 640),
        mask_count=1,
    )
    viewer = harness.viewer
    info = viewer.listMasksForImage()[0]
    layer = viewer.mask_service.assets.get_layer(harness.mask_ids[0])
    try:
        assert info.scene_id is not None
        assert info.layer_id is not None
        assert layer is not None
        assert viewer.setLayerInteractionPolicy(
            info.scene_id,
            info.layer_id,
            QPaneLayerInteractionPolicy(
                selectable=True,
                movable=True,
                pixel_editable=True,
            ),
        )
        assert viewer.setSelectedLayer(info.scene_id, info.layer_id)
        assert viewer.setLayerPlacement(
            info.scene_id,
            info.layer_id,
            QRectF(40.0, 30.0, 720.0, 510.0),
        )

        def paint_soft_mask(pixels: np.ndarray, _image: QImage) -> None:
            """Paint a nonuniform scalar payload with transparent holes."""
            pixels.fill(0)
            ramp = np.linspace(16, 255, 240, dtype=np.uint8)
            pixels[140:340, 180:420] = ramp[np.newaxis, :]
            pixels[210:250, 260:320] = 0

        layer.surface.mutate(paint_soft_mask)
        viewer.invalidateActiveMaskCache()
        viewer.markDirty()
        viewer.update()
        assert harness.wait_for_mask_render_idle()
        selection_pixels = np.linspace(32, 224, 240, dtype=np.uint8)
        selection = numpy_to_qimage_grayscale8(
            np.repeat(selection_pixels[np.newaxis, :], 200, axis=0)
        )
        assert viewer.setPixelSelection(selection, QRect(180, 140, 240, 200))
        coordinates = viewer.activeMaskLayerCoordinates()
        source = coordinates.source_to_panel(QPoint(360, 280))
        destination = coordinates.source_to_panel(QPoint(500, 220))
        assert source is not None
        assert destination is not None
        viewer.setControlMode(viewer.CONTROL_MODE_MOVE)
        QTest.mousePress(viewer, Qt.LeftButton, Qt.NoModifier, source.toPoint())
        QTest.mouseMove(viewer, destination.toPoint(), delay=0)
        harness.drain_events()
        QTest.mouseRelease(
            viewer,
            Qt.LeftButton,
            Qt.NoModifier,
            destination.toPoint(),
        )
        harness.drain_events()
        renderer = viewer.view().presenter.renderer
        viewer.markDirty()
        viewer.update()
        harness.drain_events()
        floating = renderer.get_base_buffer()
        assert floating is not None
        floating_pixels = qimage_to_numpy_argb32(floating.copy())

        assert viewer.anchorFloatingPixels()
        assert harness.wait_for_mask_render_idle()
        harness.drain_events()
        committed = renderer.get_base_buffer()
        assert committed is not None
        np.testing.assert_array_equal(
            floating_pixels,
            qimage_to_numpy_argb32(committed.copy()),
        )
    finally:
        harness.close()


def test_rgba_preview_is_pixel_identical_to_commit(qapp: QApplication) -> None:
    """Premultiplied RGBA floating content must use the same rendered transition."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(640, 480),
        widget_size=QSize(800, 600),
        mask_count=1,
    )
    viewer = harness.viewer
    try:
        scene = viewer.currentScene()
        assert scene is not None
        image = QImage(640, 480, QImage.Format_ARGB32_Premultiplied)
        image.fill(QColor(0, 0, 0, 0))
        painter_color = QColor(220, 70, 130, 176)
        for y in range(120, 280):
            for x in range(140, 340):
                if (x + y) % 9:
                    image.setPixelColor(x, y, painter_color)
        layer_id = viewer.addEditableRasterLayer(
            image,
            interaction=QPaneLayerInteractionPolicy(
                selectable=True,
                movable=True,
                pixel_editable=True,
            ),
        )
        assert layer_id is not None
        assert viewer.setSelectedLayer(scene.scene_id, layer_id)
        selection = QImage(200, 160, QImage.Format_Grayscale8)
        selection.fill(192)
        assert viewer.setPixelSelection(selection, QRect(140, 120, 200, 160))
        source = viewer.imageToPanelPoint(QPoint(240, 200))
        destination = viewer.imageToPanelPoint(QPoint(390, 260))
        assert source is not None
        assert destination is not None
        viewer.setControlMode(viewer.CONTROL_MODE_MOVE)
        QTest.mousePress(viewer, Qt.LeftButton, Qt.NoModifier, source.toPoint())
        QTest.mouseMove(viewer, destination.toPoint(), delay=0)
        harness.drain_events()
        QTest.mouseRelease(
            viewer,
            Qt.LeftButton,
            Qt.NoModifier,
            destination.toPoint(),
        )
        harness.drain_events()
        renderer = viewer.view().presenter.renderer
        viewer.markDirty()
        viewer.update()
        harness.drain_events()
        floating = renderer.get_base_buffer()
        assert floating is not None
        floating_pixels = qimage_to_numpy_argb32(floating.copy())

        assert viewer.anchorFloatingPixels()
        harness.drain_events()
        committed = renderer.get_base_buffer()
        assert committed is not None
        np.testing.assert_array_equal(
            floating_pixels,
            qimage_to_numpy_argb32(committed.copy()),
        )
    finally:
        harness.close()


def _trim_occupied(pixels: np.ndarray) -> np.ndarray:
    """Return the smallest array containing every nonzero pixel."""
    rows, columns = np.nonzero(pixels)
    assert rows.size > 0
    return pixels[
        rows.min() : rows.max() + 1,
        columns.min() : columns.max() + 1,
    ]
