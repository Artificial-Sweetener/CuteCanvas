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
"""Mounted adversarial proof for shared color and selection paint targets."""

from __future__ import annotations

import statistics
import time

import numpy as np
from cutecanvas import (
    BrushPreset,
    CuteCanvas,
    LayerPolicy,
    RasterExtentPolicy,
)
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qpane.raster.image_conversion import qimage_to_numpy_argb32

from tests.harness.mounted_qpane import MountedQPaneHarness
from tests.harness.timing import (
    INTERACTIVE_PERFORMANCE,
    absolute_latency_assertions_are_isolated,
    interaction_clock,
    stable_latency_samples,
)

pytestmark = INTERACTIVE_PERFORMANCE

_MEDIAN_POINTER_BUDGET_MS = 16.0
_ISOLATED_POINTER_CEILING_MS = 100.0


def test_brush_on_noneditable_selection_creates_and_selects_real_paint_layer(
    qapp: QApplication,
) -> None:
    """The first brush gesture visibly provisions its actual raster destination."""
    viewer = CuteCanvas()
    source = QImage(128, 96, QImage.Format.Format_ARGB32_Premultiplied)
    source.fill(QColor(30, 45, 65, 255))
    paint_color = QColor(240, 75, 125, 255)
    try:
        viewer.resize(640, 480)
        viewer.show()
        viewer.createCompositionFromImage(
            source,
            title="Automatic brush destination",
            interaction=LayerPolicy(
                selectable=True,
                movable=True,
                pixel_editable=False,
            ),
        )
        scene = viewer.currentScene()
        assert scene is not None
        source_layer_id = scene.layers[0].layer_id
        assert viewer.setSelectedLayer(scene.scene_id, source_layer_id)
        viewer.setPaintColor(paint_color)
        viewer.setBrushPreset(BrushPreset(size=3.0, hardness=1.0))
        viewer.setControlMode(viewer.CONTROL_MODE_DRAW_BRUSH)
        viewer.setZoomFit()
        qapp.processEvents()
        panel_point = viewer.view().scene_to_panel_point(QPointF(80.0, 48.0))
        assert panel_point is not None

        QTest.mouseClick(
            viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            panel_point.toPoint(),
        )
        qapp.processEvents()

        updated = viewer.currentScene()
        selected = viewer.selectedLayer()
        target = viewer.paintTargetState()
        assert updated is not None and len(updated.layers) == 2
        assert selected is not None and selected.layer_id != source_layer_id
        assert target is not None and target.layer_id == selected.layer_id
        assert [layer.layer_id for layer in updated.layers] == [
            source_layer_id,
            selected.layer_id,
        ]
        painted = viewer.editableRasterLayerImage(
            updated.scene_id,
            selected.layer_id,
        )
        assert painted is not None
        assert painted.pixelColor(80, 48) == paint_color

        assert viewer.undoSceneEdit()
        restored = viewer.editableRasterLayerImage(
            updated.scene_id,
            selected.layer_id,
        )
        assert restored is not None and restored.pixelColor(80, 48).alpha() == 0
        assert viewer.undoSceneEdit()
        assert viewer.currentScene() is not None
        assert [layer.layer_id for layer in viewer.currentScene().layers] == [
            source_layer_id
        ]
    finally:
        viewer.close()
        viewer.deleteLater()
        qapp.processEvents()


def test_mounted_textured_color_paint_is_responsive_exact_and_transactional(
    qapp: QApplication,
) -> None:
    """An 8K expanding paint target must survive hostile input and exact replay."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(8192, 2048),
        widget_size=QSize(1024, 320),
        cache_budget_mb=256,
    )
    viewer = harness.viewer
    try:
        scene = viewer.currentScene()
        assert scene is not None
        layer_id = viewer.createPaintLayer(
            QSize(64, 64),
            label="Abuse paint",
            extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
        )
        assert layer_id is not None
        viewer.setPaintColor(QColor(25, 150, 235, 220))
        viewer.setBrushPreset(
            BrushPreset(
                name="Textured proof",
                size=72.0,
                hardness=0.35,
                opacity=0.8,
                flow=0.65,
                spacing=0.18,
                smoothing=0.12,
                texture_strength=0.55,
                texture_scale=5.0,
                texture_seed=918,
            )
        )
        viewer.setControlMode(viewer.CONTROL_MODE_DRAW_BRUSH)
        harness.drain_events()
        before = viewer.editableRasterLayerImage(scene.scene_id, layer_id)
        assert before is not None

        start = QPoint(48, 160)
        QTest.mousePress(viewer, Qt.LeftButton, Qt.NoModifier, start)
        latencies: list[float] = []
        final = start
        for index in range(180):
            final = QPoint(
                48 + round(index * 920 / 179),
                160 + ((index * 29) % 23) - 11,
            )
            started = interaction_clock()
            QTest.mouseMove(viewer, final, delay=0)
            harness.drain_events()
            latencies.append((interaction_clock() - started) * 1000.0)
        QTest.mouseRelease(viewer, Qt.LeftButton, Qt.NoModifier, final)
        harness.drain_events()
        assert harness.wait_for_raster_render_idle()

        painted = viewer.editableRasterLayerImage(scene.scene_id, layer_id)
        state = viewer.rasterSurfaceState(scene.scene_id, layer_id)
        assert painted is not None and painted != before
        assert state is not None and state.bounds.width() > 7000
        painted_pixels = qimage_to_numpy_argb32(painted)
        assert np.count_nonzero(painted_pixels[:, :, 3]) > 10_000
        cache_snapshot = viewer._state.cache_coordinator.snapshot()
        brush_cache = cache_snapshot["consumers"]["brush_tips"]
        assert brush_cache["usage_bytes"] <= 8 * 1024 * 1024
        assert statistics.median(latencies) < _MEDIAN_POINTER_BUDGET_MS
        if absolute_latency_assertions_are_isolated():
            assert max(latencies) < _ISOLATED_POINTER_CEILING_MS

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

        QTest.mousePress(viewer, Qt.LeftButton, Qt.NoModifier, QPoint(200, 100))
        QTest.mouseMove(viewer, QPoint(600, 100), delay=0)
        harness.drain_events()
        QTest.keyClick(viewer, Qt.Key_Escape)
        harness.drain_events()
        cancelled = viewer.editableRasterLayerImage(scene.scene_id, layer_id)
        assert cancelled == painted

        assert viewer.undoSceneEdit()
        undone = viewer.editableRasterLayerImage(scene.scene_id, layer_id)
        assert undone == before
        assert viewer.redoSceneEdit()
        redone = viewer.editableRasterLayerImage(scene.scene_id, layer_id)
        assert redone == painted
    finally:
        harness.close()


def test_mounted_selection_paint_and_stale_target_cancel_without_residue(
    qapp: QApplication,
) -> None:
    """Selection paint and invalidation must remain atomic under real input."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(2048, 2048),
        widget_size=QSize(640, 640),
        cache_budget_mb=64,
    )
    viewer = harness.viewer
    try:
        assert viewer.setPixelSelectionPaintTarget()
        viewer.setBrushPreset(
            BrushPreset(
                name="Large selection",
                size=1000.0,
                hardness=0.2,
                opacity=0.7,
                flow=0.8,
            )
        )
        viewer.setControlMode(viewer.CONTROL_MODE_DRAW_BRUSH)
        paint_latencies_ms: list[float] = []
        selection = None
        for sample in range(8):
            started = interaction_clock()
            QTest.mouseClick(viewer, Qt.LeftButton, Qt.NoModifier, QPoint(320, 320))
            harness.drain_events()
            paint_latencies_ms.append((interaction_clock() - started) * 1000.0)
            selection = viewer.pixelSelectionState()
            assert selection is not None and selection.coverage is not None
            assert selection.bounds is not None
            assert selection.bounds.width() >= 990
            if sample < 7:
                assert viewer.undoSceneEdit()
                undone = viewer.pixelSelectionState()
                assert undone is not None and not undone.has_selection
        assert max(stable_latency_samples(paint_latencies_ms)) < 100.0
        assert selection is not None
        assert viewer.undoSceneEdit()
        undone = viewer.pixelSelectionState()
        assert undone is not None and not undone.has_selection
        assert viewer.redoSceneEdit()
        restored = viewer.pixelSelectionState()
        assert restored is not None
        assert restored.bounds == selection.bounds
        assert restored.coverage == selection.coverage

        QTest.mousePress(viewer, Qt.LeftButton, Qt.NoModifier, QPoint(250, 250))
        QTest.mouseMove(viewer, QPoint(390, 390), delay=0)
        harness.drain_events()
        composition_id = viewer.currentCompositionID()
        assert composition_id is not None
        viewer.removeComposition(composition_id)
        harness.drain_events()
        assert viewer.paintTargetState() is None
    finally:
        harness.close()


def test_empty_composition_mask_paint_is_responsive_and_exact(
    qapp: QApplication,
) -> None:
    """A mask in an image-free document must paint and replay through generic layers."""
    viewer = CuteCanvas(features=("mask",))
    viewer.resize(640, 640)
    viewer.show()
    try:
        viewer.createComposition(QRectF(0.0, 0.0, 2048.0, 2048.0))
        mask_id = viewer.createBlankMask(QSize(2048, 2048))
        scene = viewer.currentScene()
        assert mask_id is not None and scene is not None
        layer = next(item for item in scene.layers if item.source_id == mask_id)
        viewer.setLayerInteractionPolicy(
            scene.scene_id,
            layer.layer_id,
            LayerPolicy(
                selectable=True,
                movable=True,
                pixel_editable=True,
            ),
        )
        assert viewer.setActiveMaskID(mask_id)
        selected = viewer.selectedLayer()
        assert selected is not None and selected.layer_id == layer.layer_id
        assert viewer.setPaintTarget(scene.scene_id, layer.layer_id)
        viewer.setBrushPreset(
            BrushPreset(
                name="Composition mask proof",
                size=96.0,
                hardness=0.6,
                spacing=0.16,
            )
        )
        viewer.setControlMode(viewer.CONTROL_MODE_DRAW_BRUSH)
        qapp.processEvents()
        before = viewer.getActiveMaskImage()
        assert before is not None

        start = QPoint(80, 320)
        QTest.mousePress(viewer, Qt.LeftButton, Qt.NoModifier, start)
        latencies: list[float] = []
        final = start
        for index in range(120):
            final = QPoint(80 + round(index * 480 / 119), 320 + index % 7 - 3)
            started = interaction_clock()
            QTest.mouseMove(viewer, final, delay=0)
            qapp.processEvents()
            latencies.append((interaction_clock() - started) * 1000.0)
        QTest.mouseRelease(viewer, Qt.LeftButton, Qt.NoModifier, final)
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            qapp.processEvents()
            undo_state = viewer.getMaskUndoState(mask_id)
            if (
                undo_state is not None
                and undo_state.undo_depth == 1
                and not viewer.mask_service.hasPendingRenderWork()
            ):
                break
            QTest.qWait(1)
        undo_state = viewer.getMaskUndoState(mask_id)
        assert undo_state is not None and undo_state.undo_depth == 1

        painted = viewer.getActiveMaskImage()
        assert painted is not None and painted != before
        assert statistics.median(latencies) < _MEDIAN_POINTER_BUDGET_MS
        if absolute_latency_assertions_are_isolated():
            assert max(latencies) < _ISOLATED_POINTER_CEILING_MS
        assert viewer.undoSceneEdit()
        assert viewer.getActiveMaskImage() == before
        assert viewer.redoSceneEdit()
        assert viewer.getActiveMaskImage() == painted
    finally:
        viewer.close()
        viewer.deleteLater()
        qapp.processEvents()
