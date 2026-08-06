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
"""Adversarial interaction, revision, and latency proof for Clone Stamp."""

from __future__ import annotations

import statistics
import uuid

import numpy as np
from cutecanvas import (
    BrushPreset,
    CloneStampAlignment,
    CloneStampSampleMode,
    CloneStampTransform,
    CuteCanvas,
    EditorPolicy,
    LayerPolicy,
    NonEditablePaintPolicy,
)
from cutecanvas.painting import BrushStrokeSegment
from cutecanvas.painting.tools.clone_feedback import CloneStampFeedbackProjector
from cutecanvas.resources import ProjectResourceReference
from cutecanvas_test_support.harness.mounted_qpane import MountedQPaneHarness
from cutecanvas_test_support.harness.timing import INTERACTIVE_PERFORMANCE
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QTransform
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qpane.sdk.raster import qimage_to_numpy_argb32
from qpane.sdk.rendering import LayerSourcePoint, PanelPoint, ScenePoint
from qpane.sdk.scene import RasterBounds

pytestmark = INTERACTIVE_PERFORMANCE
from cutecanvas_test_support.harness.timing import (
    absolute_latency_assertions_are_isolated,
    interaction_clock,
    stable_latency_samples,
)

_MEDIAN_SEGMENT_BUDGET_MS = 16.0
_ISOLATED_SEGMENT_CEILING_MS = 100.0
_COMMIT_CEILING_MS = 100.0


def test_smart_source_first_stroke_creates_selects_and_paints_real_layer(
    qapp: QApplication,
) -> None:
    """A rendered smart source provisions a visible destination before painting."""
    viewer = CuteCanvas()
    source = QImage(128, 96, QImage.Format.Format_ARGB32_Premultiplied)
    source.fill(QColor(25, 45, 70, 255))
    source_color = QColor(225, 70, 135, 255)
    painter = QPainter(source)
    painter.fillRect(QRect(18, 20, 24, 24), source_color)
    painter.end()
    try:
        viewer.resize(640, 480)
        viewer.show()
        viewer.createCompositionFromImage(
            source,
            title="Rendered clone source",
            interaction=LayerPolicy(
                selectable=True,
                movable=True,
                pixel_editable=False,
            ),
        )
        scene = viewer.currentScene()
        assert scene is not None and len(scene.layers) == 1
        source_layer_id = scene.layers[0].layer_id
        assert viewer.setSelectedLayer(scene.scene_id, source_layer_id)
        transform = QTransform(1.08, 0.06, -0.04, 1.04, 12.0, 8.0)
        assert viewer.setLayerTransform(
            scene.scene_id,
            source_layer_id,
            transform,
        )
        source_scene_point = transform.map(QPointF(28.0, 30.0))
        assert viewer.setCloneStampSource(source_scene_point)
        assert viewer.cloneStampState().source is not None
        assert viewer.cloneStampState().source.layer_id == source_layer_id
        viewer.setBrushPreset(
            BrushPreset(
                name="Smart source proof",
                size=3.0,
                hardness=1.0,
                spacing=0.1,
            )
        )
        assert viewer.setCloneStampTransform(
            CloneStampTransform(
                rotation_degrees=12.5,
                scale_x=1.1,
                scale_y=0.9,
                mirror_horizontal=True,
            )
        )
        viewer.setControlMode(viewer.CONTROL_MODE_CLONE_STAMP)
        viewer.setZoomFit()
        qapp.processEvents()

        destination_panel = viewer.view().scene_to_panel_point(QPointF(92.0, 58.0))
        assert destination_panel is not None
        QTest.mouseClick(
            viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            destination_panel.toPoint(),
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
        assert painted.pixelColor(92, 58) == source_color
        assert viewer.cloneStampState().source is not None
        assert viewer.cloneStampState().source.layer_id == source_layer_id

        assert viewer.undoSceneEdit()
        restored = viewer.editableRasterLayerImage(
            updated.scene_id,
            selected.layer_id,
        )
        assert restored is not None and restored.pixelColor(92, 58).alpha() == 0
        assert viewer.currentScene() is not None
        assert len(viewer.currentScene().layers) == 2
        assert viewer.undoSceneEdit()
        assert viewer.currentScene() is not None
        assert [layer.layer_id for layer in viewer.currentScene().layers] == [
            source_layer_id
        ]
    finally:
        viewer.close()
        viewer.deleteLater()
        qapp.processEvents()


def test_host_can_reject_automatic_paint_layer_creation(
    qapp: QApplication,
) -> None:
    """Host policy can retain a non-editable selection without hidden painting."""
    viewer = CuteCanvas()
    source = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
    source.fill(QColor(80, 120, 180, 255))
    try:
        viewer.resize(480, 360)
        viewer.show()
        viewer.createCompositionFromImage(
            source,
            title="Rejected paint provisioning",
            interaction=LayerPolicy(selectable=True),
        )
        scene = viewer.currentScene()
        assert scene is not None
        source_layer_id = scene.layers[0].layer_id
        assert viewer.setEditorPolicy(
            EditorPolicy(
                noneditable_paint=NonEditablePaintPolicy.REJECT,
            )
        )
        assert viewer.setSelectedLayer(scene.scene_id, source_layer_id)
        assert viewer.setCloneStampSource(QPointF(16.0, 16.0))
        viewer.setControlMode(viewer.CONTROL_MODE_CLONE_STAMP)
        viewer.setZoomFit()
        qapp.processEvents()
        destination = viewer.view().scene_to_panel_point(QPointF(48.0, 48.0))
        assert destination is not None

        QTest.mouseClick(
            viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            destination.toPoint(),
        )
        qapp.processEvents()

        unchanged = viewer.currentScene()
        selected = viewer.selectedLayer()
        assert unchanged is not None and len(unchanged.layers) == 1
        assert selected is not None and selected.layer_id == source_layer_id
        assert viewer.paintTargetState() is None
    finally:
        viewer.close()
        viewer.deleteLater()
        qapp.processEvents()


def test_clone_source_scopes_render_exact_visible_layer_ranges(
    qapp: QApplication,
) -> None:
    """Layer, layer-and-below, and composition scopes share one renderer path."""
    viewer = CuteCanvas()
    try:
        viewer.createComposition(
            QRectF(0.0, 0.0, 64.0, 64.0),
            title="Clone source scopes",
        )
        public_scene = viewer.currentScene()
        assert public_scene is not None
        background = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
        background.fill(QColor(220, 20, 20, 255))
        anchor = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
        anchor.fill(QColor(20, 220, 20, 128))
        upper = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
        upper.fill(QColor(20, 20, 220, 255))
        target = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
        target.fill(Qt.GlobalColor.transparent)
        policy = LayerPolicy(selectable=True, pixel_editable=True)
        background_id = viewer.addEditableRasterLayer(
            background,
            interaction=policy,
            label="Background",
        )
        anchor_id = viewer.addEditableRasterLayer(
            anchor,
            interaction=policy,
            label="Source",
        )
        upper_id = viewer.addEditableRasterLayer(
            upper,
            interaction=policy,
            label="Upper",
        )
        target_id = viewer.addEditableRasterLayer(
            target,
            interaction=policy,
            label="Target",
        )
        assert all(
            layer_id is not None
            for layer_id in (background_id, anchor_id, upper_id, target_id)
        )
        assert anchor_id is not None
        assert upper_id is not None
        assert target_id is not None
        assert viewer.setSelectedLayer(public_scene.scene_id, anchor_id)
        assert viewer.setCloneStampSource(QPointF(12.0, 12.0))
        assert viewer.setSelectedLayer(public_scene.scene_id, target_id)
        viewer.setControlMode(viewer.CONTROL_MODE_CLONE_STAMP)
        viewer.setCloneStampAlignment(CloneStampAlignment.UNALIGNED)
        viewer.setBrushPreset(BrushPreset(size=1.0, hardness=1.0))
        painting = viewer.paintingCoordinator()

        destinations = (
            (CloneStampSampleMode.ANCHORED_LAYER, QPointF(30.0, 12.0)),
            (
                CloneStampSampleMode.ANCHORED_LAYER_AND_BELOW,
                QPointF(34.0, 12.0),
            ),
            (CloneStampSampleMode.VISIBLE_COMPOSITE, QPointF(38.0, 12.0)),
        )
        for mode, destination in destinations:
            viewer.setCloneStampSampleMode(mode)
            assert painting.begin()
            assert painting.apply(
                BrushStrokeSegment.fixed(
                    (destination.x(), destination.y()),
                    (destination.x(), destination.y()),
                    1.0,
                    False,
                )
            )
            assert painting.commit()

        painted = viewer.editableRasterLayerImage(public_scene.scene_id, target_id)
        assert painted is not None
        layer_only = painted.pixelColor(30, 12)
        layer_and_below = painted.pixelColor(34, 12)
        visible = painted.pixelColor(38, 12)
        assert layer_only.alpha() == 128
        assert abs(layer_only.red() - 20) <= 1
        assert abs(layer_only.green() - 220) <= 1
        assert abs(layer_only.blue() - 20) <= 1
        assert layer_and_below.alpha() == 255
        assert abs(layer_and_below.red() - 120) <= 2
        assert abs(layer_and_below.green() - 120) <= 2
        assert layer_and_below.blue() <= 20
        assert visible == QColor(20, 20, 220, 255)

        assert viewer.setLayerVisible(public_scene.scene_id, upper_id, False)
        assert viewer.setCloneStampSource(QPointF(12.0, 12.0))
        assert painting.begin()
        assert painting.apply(
            BrushStrokeSegment.fixed((42.0, 12.0), (42.0, 12.0), 1.0, False)
        )
        assert painting.commit()
        hidden_excluded = viewer.editableRasterLayerImage(
            public_scene.scene_id,
            target_id,
        )
        assert hidden_excluded is not None
        hidden_sample = hidden_excluded.pixelColor(42, 12)
        assert hidden_sample.alpha() == 255
        assert abs(hidden_sample.red() - 120) <= 2
        assert abs(hidden_sample.green() - 120) <= 2
        assert hidden_sample.blue() <= 20
    finally:
        viewer.close()
        viewer.deleteLater()
        qapp.processEvents()


def test_source_revision_change_cancels_complete_clone_stroke_without_residue(
    qapp: QApplication,
) -> None:
    """A mid-stroke source revision change rolls back every destination tile."""
    viewer = CuteCanvas()
    try:
        viewer.createComposition(QRectF(0.0, 0.0, 64.0, 64.0))
        public_scene = viewer.currentScene()
        assert public_scene is not None
        source = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
        source.fill(QColor(215, 50, 80, 255))
        target = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
        target.fill(Qt.GlobalColor.transparent)
        policy = LayerPolicy(selectable=True, pixel_editable=True)
        source_id = viewer.addEditableRasterLayer(
            source,
            interaction=policy,
            label="Changing source",
        )
        target_id = viewer.addEditableRasterLayer(
            target,
            interaction=policy,
            label="Protected destination",
        )
        assert source_id is not None and target_id is not None
        assert viewer.setSelectedLayer(public_scene.scene_id, source_id)
        assert viewer.setCloneStampSource(QPointF(8.0, 8.0))
        assert viewer.setSelectedLayer(public_scene.scene_id, target_id)
        viewer.setControlMode(viewer.CONTROL_MODE_CLONE_STAMP)
        viewer.setCloneStampAlignment(CloneStampAlignment.UNALIGNED)
        viewer.setCloneStampTransform(
            CloneStampTransform(
                rotation_degrees=23.0,
                scale_x=1.2,
                scale_y=0.85,
            )
        )
        viewer.setBrushPreset(BrushPreset(size=3.0, hardness=1.0))
        painting = viewer.paintingCoordinator()
        assert painting.begin()
        assert painting.apply(
            BrushStrokeSegment.fixed((30.0, 20.0), (30.0, 20.0), 3.0, False)
        )

        scene = viewer.sceneMutationCoordinator().active_scene()
        assert scene is not None
        source_layer = next(
            layer for layer in scene.layers if layer.layer_id == source_id
        )
        reference = source_layer.source
        assert isinstance(reference, ProjectResourceReference)
        asset = viewer._editable_raster_assets.get(reference.resource_id)
        assert asset is not None
        replacement = np.zeros((1, 1, 4), dtype=np.uint8)
        replacement[0, 0] = (230, 90, 40, 255)
        assert asset.surface.restore_patch(
            RasterBounds(8, 8, 1, 1),
            replacement,
        )

        assert not painting.apply(
            BrushStrokeSegment.fixed((34.0, 20.0), (34.0, 20.0), 3.0, False)
        )
        assert not painting.commit()
        restored = viewer.editableRasterLayerImage(
            public_scene.scene_id,
            target_id,
        )
        assert restored is not None
        assert restored.pixelColor(30, 20).alpha() == 0
        assert restored.pixelColor(34, 20).alpha() == 0
    finally:
        viewer.close()
        viewer.deleteLater()
        qapp.processEvents()


def test_rapid_scope_switching_never_reanchors_source_to_destination(
    qapp: QApplication,
) -> None:
    """Source identity stays independent through hostile configuration churn."""
    viewer = CuteCanvas()
    source = QImage(96, 64, QImage.Format.Format_ARGB32_Premultiplied)
    source.fill(QColor(35, 90, 180, 255))
    destination = QImage(96, 64, QImage.Format.Format_ARGB32_Premultiplied)
    destination.fill(Qt.GlobalColor.transparent)
    try:
        viewer.createCompositionFromImage(
            source,
            interaction=LayerPolicy(selectable=True, movable=True),
        )
        scene = viewer.currentScene()
        assert scene is not None
        source_id = scene.layers[0].layer_id
        destination_id = viewer.addEditableRasterLayer(
            destination,
            interaction=LayerPolicy(selectable=True, pixel_editable=True),
        )
        assert destination_id is not None
        assert viewer.setSelectedLayer(scene.scene_id, source_id)
        assert viewer.setCloneStampSource(QPointF(16.0, 16.0))
        assert viewer.setSelectedLayer(scene.scene_id, destination_id)
        modes = (
            CloneStampSampleMode.VISIBLE_COMPOSITE,
            CloneStampSampleMode.ANCHORED_LAYER_AND_BELOW,
            CloneStampSampleMode.ANCHORED_LAYER,
        )
        latencies_ms: list[float] = []

        for index in range(300):
            started = interaction_clock()
            viewer.setCloneStampSampleMode(modes[index % len(modes)])
            latencies_ms.append((interaction_clock() - started) * 1000.0)
            state = viewer.cloneStampState()
            assert state.source is not None
            assert state.source.layer_id == source_id
            selected = viewer.selectedLayer()
            assert selected is not None and selected.layer_id == destination_id

        stable = stable_latency_samples(latencies_ms)
        assert statistics.median(stable) < 1.0
        if absolute_latency_assertions_are_isolated():
            assert max(stable) < 20.0
    finally:
        viewer.close()
        viewer.deleteLater()
        qapp.processEvents()


def test_mounted_clone_source_stroke_navigation_and_history_are_atomic(
    qapp: QApplication,
) -> None:
    """Real pointer input must source, paint, suspend, and replay without residue."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(512, 512),
        widget_size=QSize(512, 512),
        cache_budget_mb=64,
    )
    viewer = harness.viewer
    source_image = _source_band(QSize(512, 512), split=220)
    try:
        scene = viewer.currentScene()
        assert scene is not None
        layer_id = viewer.addEditableRasterLayer(
            source_image,
            interaction=LayerPolicy(
                selectable=True,
                movable=True,
                pixel_editable=True,
            ),
            label="Mounted clone",
        )
        assert layer_id is not None
        assert viewer.setSelectedLayer(scene.scene_id, layer_id)
        assert viewer.setPaintTarget(scene.scene_id, layer_id)
        viewer.setBrushPreset(
            BrushPreset(
                name="Mounted clone proof",
                size=34.0,
                hardness=1.0,
                spacing=0.12,
            )
        )
        assert viewer.setCloneStampTransform(
            CloneStampTransform(
                rotation_degrees=12.5,
                scale_x=1.1,
                scale_y=0.9,
                mirror_horizontal=True,
            )
        )
        viewer.setControlMode(viewer.CONTROL_MODE_CLONE_STAMP)
        harness.drain_events()
        before = viewer.editableRasterLayerImage(scene.scene_id, layer_id)
        assert before is not None
        undo_before_source = viewer.sceneEditUndoAvailable()

        QTest.mouseClick(
            viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.AltModifier,
            QPoint(90, 256),
        )
        harness.drain_events()
        assert viewer.cloneStampState().source_set
        source_anchor = viewer.cloneStampState().source
        assert source_anchor is not None
        assert viewer.sceneEditUndoAvailable() is undo_before_source

        destination = QPoint(340, 256)
        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, Qt.NoModifier, destination)
        QTest.mouseMove(viewer, QPoint(410, 256), delay=0)
        harness.drain_events()
        QTest.keyPress(viewer, Qt.Key.Key_Space)
        harness.drain_events()
        QTest.mouseRelease(
            viewer,
            Qt.MouseButton.LeftButton,
            Qt.NoModifier,
            QPoint(410, 256),
        )
        QTest.keyRelease(viewer, Qt.Key.Key_Space)
        harness.drain_events()

        assert viewer.getControlMode() == viewer.CONTROL_MODE_CLONE_STAMP
        assert viewer.cloneStampState().source == source_anchor
        assert viewer.sceneEditUndoAvailable()
        painted = viewer.editableRasterLayerImage(scene.scene_id, layer_id)
        assert painted is not None and painted != before
        assert painted.pixelColor(340, 256) == QColor(35, 125, 235, 255)
        assert harness.wait_for_raster_render_idle()
        renderer = viewer.view().presenter.renderer
        incremental = renderer.get_base_buffer()
        assert incremental is not None
        incremental_pixels = qimage_to_numpy_argb32(incremental.copy())
        viewer.markDirty()
        viewer.update()
        harness.drain_events()
        assert harness.wait_for_raster_render_idle()
        repaired = renderer.get_base_buffer()
        assert repaired is not None
        np.testing.assert_array_equal(
            incremental_pixels,
            qimage_to_numpy_argb32(repaired.copy()),
        )
        assert viewer.undoSceneEdit()
        assert viewer.editableRasterLayerImage(scene.scene_id, layer_id) == before
        assert viewer.redoSceneEdit()
        assert viewer.editableRasterLayerImage(scene.scene_id, layer_id) == painted
    finally:
        harness.close()


def test_rasterized_selected_layer_becomes_clone_target_without_reselection(
    qapp: QApplication,
) -> None:
    """Rasterization must reconcile the unchanged selection with Clone Stamp."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(512, 512),
        widget_size=QSize(512, 512),
        cache_budget_mb=64,
    )
    viewer = harness.viewer
    try:
        scene = viewer.currentScene()
        assert scene is not None
        layer_id = viewer.placeEmbeddedAsset(
            _source_band(QSize(256, 256), split=128),
            placement=QRectF(128.0, 128.0, 256.0, 256.0),
            interaction=LayerPolicy(
                selectable=True,
                movable=True,
                pixel_editable=True,
            ),
            label="Rasterize for clone",
        )
        assert layer_id is not None
        assert viewer.setSelectedLayer(scene.scene_id, layer_id)
        viewer.setControlMode(viewer.CONTROL_MODE_CLONE_STAMP)
        harness.drain_events()
        assert viewer.paintTargetState() is None

        completions: list[tuple[object, ...]] = []
        viewer.layerRasterizationCompleted.connect(
            lambda *values: completions.append(tuple(values))
        )
        request_id = viewer.rasterizeLayer(scene.scene_id, layer_id)
        assert request_id is not None
        deadline = interaction_clock() + 3.0
        while interaction_clock() < deadline and not any(
            completion[0] == request_id for completion in completions
        ):
            harness.drain_events(wait_ms=1)
        matching = [
            completion for completion in completions if completion[0] == request_id
        ]
        assert matching and matching[-1][3] is True

        target = viewer.paintTargetState()
        assert target is not None and target.layer_id == layer_id
        source_panel = viewer.view().layer_source_to_panel_point(
            scene.scene_id,
            layer_id,
            QPointF(64.0, 128.0),
        )
        assert source_panel is not None
        QTest.mouseClick(
            viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.AltModifier,
            source_panel.toPoint(),
        )
        harness.drain_events()
        assert viewer.cloneStampState().source_set
        destination_panel = viewer.view().layer_source_to_panel_point(
            scene.scene_id,
            layer_id,
            QPointF(192.0, 128.0),
        )
        assert destination_panel is not None
        QTest.mouseClick(
            viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            destination_panel.toPoint(),
        )
        harness.drain_events()
        painted = viewer.editableRasterLayerImage(scene.scene_id, layer_id)
        assert painted is not None
        assert painted.pixelColor(192, 128) == QColor(35, 125, 235, 255)
        assert viewer.undoSceneEdit()
        restored = viewer.editableRasterLayerImage(scene.scene_id, layer_id)
        assert restored is not None and restored.pixelColor(192, 128).alpha() == 0
    finally:
        harness.close()


def test_mounted_clone_marker_and_sample_share_transformed_offset_coordinates(
    qapp: QApplication,
) -> None:
    """Marker input and sampled pixels must share QPane projection in every view."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(512, 512),
        widget_size=QSize(512, 512),
        cache_budget_mb=64,
    )
    viewer = harness.viewer
    image = QImage(64, 32, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    source_color = QColor(210, 45, 135, 255)
    painter = QPainter(image)
    painter.fillRect(QRect(7, 14, 5, 5), source_color)
    painter.end()
    try:
        public_scene = viewer.currentScene()
        assert public_scene is not None
        layer_id = viewer.addEditableRasterLayer(
            image,
            interaction=LayerPolicy(
                selectable=True,
                movable=True,
                pixel_editable=True,
            ),
            label="Projected clone",
        )
        assert layer_id is not None
        assert viewer.setSelectedLayer(public_scene.scene_id, layer_id)
        assert viewer.setPaintTarget(public_scene.scene_id, layer_id)
        _wait_for_raster_bounds(
            harness,
            public_scene.scene_id,
            layer_id,
            QRect(-7, -5, 72, 40),
        )
        transform = QTransform(1.25, 0.16, -0.09, 1.18, 118.0, 96.0)
        assert viewer.setLayerTransform(
            public_scene.scene_id,
            layer_id,
            transform,
        )
        viewer.setBrushPreset(
            BrushPreset(
                name="Coordinate projection proof",
                size=1.0,
                hardness=1.0,
                spacing=0.1,
            )
        )
        viewer.setControlMode(viewer.CONTROL_MODE_CLONE_STAMP)
        viewer.setZoom1To1()
        viewer.setPan(QPointF(18.5, -12.25))
        harness.drain_events()

        resolved_scene = viewer.sceneMutationCoordinator().active_scene()
        assert resolved_scene is not None
        coordinates = viewer.coordinateSystem()
        assert coordinates is viewer.view().coordinates
        source = LayerSourcePoint(
            resolved_scene.scene_id,
            layer_id,
            16.0,
            21.0,
        )
        source_panel = coordinates.layer_source_to_panel(source)
        assert source_panel is not None
        source_click = source_panel.to_qt().toPoint()
        QTest.mouseClick(
            viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.AltModifier,
            source_click,
        )
        harness.drain_events()

        clicked_source = coordinates.panel_to_layer_source(
            resolved_scene.scene_id,
            layer_id,
            PanelPoint.from_qt(source_click),
        )
        assert clicked_source is not None
        source_state = viewer.cloneStampState().source
        assert source_state is not None
        assert source_state.layer_position == (clicked_source.x, clicked_source.y)
        expected_scene = coordinates.layer_source_to_scene(clicked_source)
        assert expected_scene is not None
        marker_scene = viewer.cloneStampOperation().source_scene_point()
        assert marker_scene is not None
        assert QPointF(marker_scene) == expected_scene.to_qt()
        marker_panel = viewer.cloneStampOperation().source_panel_point()
        assert marker_panel is not None
        assert (
            QPointF(marker_panel)
            == coordinates.layer_source_to_panel(clicked_source).to_qt()
        )

        viewer.setPan(QPointF(-24.75, 19.5))
        harness.drain_events()
        moved_marker_panel = viewer.cloneStampOperation().source_panel_point()
        assert moved_marker_panel is not None
        assert (
            QPointF(moved_marker_panel)
            == coordinates.layer_source_to_panel(clicked_source).to_qt()
        )
        destination = LayerSourcePoint(
            resolved_scene.scene_id,
            layer_id,
            51.0,
            21.0,
        )
        destination_panel = coordinates.layer_source_to_panel(destination)
        assert destination_panel is not None
        round_trip = coordinates.panel_to_layer_source(
            resolved_scene.scene_id,
            layer_id,
            destination_panel,
        )
        assert round_trip is not None
        assert abs(round_trip.x - destination.x) < 1e-9
        assert abs(round_trip.y - destination.y) < 1e-9

        QTest.mouseClick(
            viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            destination_panel.to_qt().toPoint(),
        )
        harness.drain_events()
        result = viewer.editableRasterLayerImage(
            public_scene.scene_id,
            layer_id,
        )
        assert result is not None
        assert result.pixelColor(51, 21) == source_color
    finally:
        harness.close()


def test_mounted_clone_source_footprint_tracks_stroke_then_restores_anchor(
    qapp: QApplication,
) -> None:
    """A real drag must move sampled-area feedback transiently and restore it."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(160, 64),
        widget_size=QSize(640, 256),
        cache_budget_mb=64,
    )
    viewer = harness.viewer
    image = QImage(160, 64, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    for x in range(160):
        image.setPixelColor(x, 24, QColor(x, 80, 180, 255))
    try:
        public_scene = viewer.currentScene()
        assert public_scene is not None
        layer_id = viewer.addEditableRasterLayer(
            image,
            interaction=LayerPolicy(
                selectable=True,
                movable=True,
                pixel_editable=True,
            ),
            label="Transient source feedback",
        )
        assert layer_id is not None
        assert viewer.setSelectedLayer(public_scene.scene_id, layer_id)
        assert viewer.setPaintTarget(public_scene.scene_id, layer_id)
        viewer.setBrushPreset(
            BrushPreset(
                name="Source feedback proof",
                size=1.0,
                hardness=1.0,
                spacing=0.1,
            )
        )
        viewer.setControlMode(viewer.CONTROL_MODE_CLONE_STAMP)
        viewer.setZoom1To1()
        assert viewer.setCloneStampSource(QPointF(20.0, 24.0))
        harness.drain_events()

        scene = viewer.sceneMutationCoordinator().active_scene()
        assert scene is not None
        coordinates = viewer.coordinateSystem()
        begin = coordinates.layer_source_to_panel(
            LayerSourcePoint(scene.scene_id, layer_id, 80.0, 24.0)
        )
        end = coordinates.layer_source_to_panel(
            LayerSourcePoint(scene.scene_id, layer_id, 100.0, 24.0)
        )
        assert begin is not None and end is not None
        operation = viewer.cloneStampOperation()

        QTest.mousePress(
            viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            begin.to_qt().toPoint(),
        )
        QTest.mouseMove(viewer, end.to_qt().toPoint())
        harness.drain_events()
        active_source = operation.source_scene_point()
        assert active_source is not None
        assert abs(active_source.x() - 40.0) < 1.0
        assert abs(active_source.y() - 24.0) < 1.0

        QTest.mouseRelease(
            viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            end.to_qt().toPoint(),
        )
        harness.drain_events()
        assert operation.source_scene_point() == QPointF(20.0, 24.0)
        result = viewer.editableRasterLayerImage(public_scene.scene_id, layer_id)
        assert result is not None
        assert result.pixelColor(100, 24) == QColor(40, 80, 180, 255)
    finally:
        harness.close()


def test_clone_source_footprint_uses_the_exact_affine_sample_mapping(
    qapp: QApplication,
) -> None:
    """Rendered source feedback must match rotated and scaled sampling geometry."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(160, 96),
        widget_size=QSize(640, 384),
        cache_budget_mb=64,
    )
    viewer = harness.viewer
    try:
        scene = viewer.currentScene()
        assert scene is not None
        layer_id = viewer.addEditableRasterLayer(
            _source_band(QSize(160, 96), split=80),
            interaction=LayerPolicy(selectable=True, pixel_editable=True),
        )
        assert layer_id is not None
        assert viewer.setSelectedLayer(scene.scene_id, layer_id)
        assert viewer.setPaintTarget(scene.scene_id, layer_id)
        assert viewer.setCloneStampSource(QPointF(40.0, 48.0))
        assert viewer.setCloneStampTransform(
            CloneStampTransform(
                rotation_degrees=90.0,
                scale_x=2.0,
                scale_y=2.0,
            )
        )
        viewer.setControlMode(viewer.CONTROL_MODE_CLONE_STAMP)
        viewer.setZoom1To1()
        viewer.setPan(QPointF(13.25, -7.5))
        harness.drain_events()

        projector = CloneStampFeedbackProjector(
            operation=viewer.cloneStampOperation(),
            coordinates=viewer.coordinateSystem(),
        )
        preview = projector.footprint(20.0)
        assert preview is not None
        coordinates = viewer.coordinateSystem()
        center = coordinates.scene_to_panel(ScenePoint(scene.scene_id, 40.0, 48.0))
        axis_x = coordinates.scene_to_panel(ScenePoint(scene.scene_id, 40.0, 43.0))
        axis_y = coordinates.scene_to_panel(ScenePoint(scene.scene_id, 45.0, 48.0))
        assert center is not None and axis_x is not None and axis_y is not None
        assert preview.center == center.to_qt()
        assert preview.axis_x == axis_x.to_qt() - center.to_qt()
        assert QPointF(preview.axis_y_x, preview.axis_y_y) == (
            axis_y.to_qt() - center.to_qt()
        )

        painting = viewer.paintingCoordinator()
        assert painting.begin()
        assert painting.apply(
            BrushStrokeSegment.fixed(
                (80.0, 48.0),
                (100.0, 48.0),
                20.0,
                False,
            )
        )
        active_preview = projector.footprint(20.0)
        active_center = coordinates.scene_to_panel(
            ScenePoint(scene.scene_id, 40.0, 38.0)
        )
        assert active_preview is not None and active_center is not None
        assert active_preview.contact
        assert active_preview.center == active_center.to_qt()
        assert painting.cancel()
        restored_preview = projector.footprint(20.0)
        assert restored_preview is not None
        assert not restored_preview.contact
        assert restored_preview.center == center.to_qt()
    finally:
        harness.close()


def test_8k_selected_layer_clone_is_sparse_stable_and_responsive(
    qapp: QApplication,
) -> None:
    """An 8K overlapping source path must stay bounded, exact, and interactive."""
    viewer = CuteCanvas()
    try:
        viewer.createComposition(QRectF(0.0, 0.0, 8192.0, 512.0))
        source_image = _source_band(QSize(8192, 512), split=4096)
        layer_id = viewer.addEditableRasterLayer(
            source_image,
            interaction=LayerPolicy(selectable=True, pixel_editable=True),
            label="8K clone",
        )
        scene = viewer.currentScene()
        assert scene is not None and layer_id is not None
        assert viewer.setSelectedLayer(scene.scene_id, layer_id)
        assert viewer.setPaintTarget(scene.scene_id, layer_id)
        assert viewer.setCloneStampSource(QPointF(4000.0, 256.0))
        assert viewer.setCloneStampTransform(
            CloneStampTransform(
                rotation_degrees=0.75,
                scale_x=1.25,
                scale_y=1.25,
                mirror_horizontal=True,
            )
        )
        viewer.setBrushPreset(
            BrushPreset(
                name="8K abuse",
                size=96.0,
                hardness=0.45,
                opacity=0.9,
                flow=0.8,
                spacing=0.18,
            )
        )
        viewer.setControlMode(viewer.CONTROL_MODE_CLONE_STAMP)
        painting = viewer.paintingCoordinator()
        before = viewer.editableRasterLayerImage(scene.scene_id, layer_id)
        assert before is not None

        assert painting.begin()
        latencies_ms: list[float] = []
        previous = (4300.0, 256.0)
        for index in range(180):
            current = (4300.0 + index * 20.0, 256.0 + (index % 5) - 2.0)
            started = interaction_clock()
            assert painting.apply(
                BrushStrokeSegment.fixed(
                    previous,
                    current,
                    96.0,
                    False,
                )
            )
            latencies_ms.append((interaction_clock() - started) * 1000.0)
            previous = current
        commit_started = interaction_clock()
        assert painting.commit()
        commit_ms = (interaction_clock() - commit_started) * 1000.0

        stable = stable_latency_samples(latencies_ms)
        assert statistics.median(stable) < _MEDIAN_SEGMENT_BUDGET_MS
        if absolute_latency_assertions_are_isolated():
            assert max(stable) < _ISOLATED_SEGMENT_CEILING_MS
        assert commit_ms < _COMMIT_CEILING_MS
        painted = viewer.editableRasterLayerImage(scene.scene_id, layer_id)
        assert painted is not None and painted != before
        pixels = qimage_to_numpy_argb32(painted)
        assert np.count_nonzero(pixels[:, 4200:, 3]) > 100_000
        assert viewer.undoSceneEdit()
        assert viewer.editableRasterLayerImage(scene.scene_id, layer_id) == before
        assert viewer.redoSceneEdit()
        assert viewer.editableRasterLayerImage(scene.scene_id, layer_id) == painted
    finally:
        viewer.close()
        viewer.deleteLater()
        qapp.processEvents()


def test_visible_composite_selection_cancel_and_stale_target_are_exact(
    qapp: QApplication,
) -> None:
    """Composite sampling must obey selection and roll back every abandoned path."""
    viewer = CuteCanvas()
    try:
        base = _source_band(QSize(4096, 1024), split=4096)
        viewer.createCompositionFromImage(
            base,
            title="Composite clone",
            label="Background",
        )
        target = QImage(4096, 1024, QImage.Format.Format_ARGB32_Premultiplied)
        target.fill(Qt.GlobalColor.transparent)
        layer_id = viewer.addEditableRasterLayer(
            target,
            interaction=LayerPolicy(selectable=True, pixel_editable=True),
            label="Composite clone",
        )
        scene = viewer.currentScene()
        assert scene is not None and layer_id is not None
        assert viewer.setSelectedLayer(scene.scene_id, layer_id)
        assert viewer.setPaintTarget(scene.scene_id, layer_id)
        assert viewer.setCloneStampSampleMode(CloneStampSampleMode.VISIBLE_COMPOSITE)
        assert viewer.setCloneStampSource(QPointF(128.0, 512.0))
        assert viewer.setCloneStampTransform(
            CloneStampTransform(
                rotation_degrees=-12.0,
                scale_x=0.8,
                scale_y=0.8,
                mirror_vertical=True,
            )
        )
        viewer.setBrushPreset(
            BrushPreset(
                name="Composite abuse",
                size=128.0,
                hardness=0.7,
                spacing=0.2,
            )
        )
        viewer.setControlMode(viewer.CONTROL_MODE_CLONE_STAMP)
        selection = QImage(500, 300, QImage.Format.Format_Grayscale8)
        selection.fill(255)
        assert viewer.setPixelSelection(selection, QRect(2600, 350, 500, 300))
        painting = viewer.paintingCoordinator()
        before = viewer.editableRasterLayerImage(scene.scene_id, layer_id)
        assert before is not None

        assert painting.begin()
        latencies_ms: list[float] = []
        previous = (2500.0, 512.0)
        for index in range(80):
            current = (2500.0 + index * 12.0, 512.0)
            started = interaction_clock()
            painting.apply(
                BrushStrokeSegment.fixed(
                    previous,
                    current,
                    128.0,
                    False,
                )
            )
            latencies_ms.append((interaction_clock() - started) * 1000.0)
            previous = current
        commit_started = interaction_clock()
        assert painting.commit()
        commit_ms = (interaction_clock() - commit_started) * 1000.0
        stable = stable_latency_samples(latencies_ms)
        assert statistics.median(stable) < _MEDIAN_SEGMENT_BUDGET_MS
        if absolute_latency_assertions_are_isolated():
            assert max(stable) < _ISOLATED_SEGMENT_CEILING_MS
        assert commit_ms < _COMMIT_CEILING_MS
        painted = viewer.editableRasterLayerImage(scene.scene_id, layer_id)
        assert painted is not None
        assert painted.pixelColor(2700, 512).alpha() > 0
        assert painted.pixelColor(3200, 512).alpha() == 0

        assert painting.begin()
        assert painting.apply(
            BrushStrokeSegment.fixed(
                (2800.0, 450.0),
                (2920.0, 450.0),
                128.0,
                False,
            )
        )
        assert painting.cancel()
        assert viewer.editableRasterLayerImage(scene.scene_id, layer_id) == painted

        assert painting.begin()
        assert painting.apply(
            BrushStrokeSegment.fixed(
                (2800.0, 580.0),
                (2920.0, 580.0),
                128.0,
                False,
            )
        )
        assert viewer.clearPaintTarget()
        assert viewer.editableRasterLayerImage(scene.scene_id, layer_id) == painted
    finally:
        viewer.close()
        viewer.deleteLater()
        qapp.processEvents()


def test_removing_clone_target_mid_stroke_restores_exact_pixels(
    qapp: QApplication,
) -> None:
    """Layer removal must abandon an active clone transaction without residue."""
    viewer = CuteCanvas()
    try:
        viewer.createComposition(QRectF(0.0, 0.0, 512.0, 256.0))
        layer_id = viewer.addEditableRasterLayer(
            _source_band(QSize(512, 256), split=220),
            interaction=LayerPolicy(
                selectable=True,
                pixel_editable=True,
                removable=True,
            ),
            label="Disposable clone target",
        )
        scene = viewer.currentScene()
        assert scene is not None and layer_id is not None
        assert viewer.setSelectedLayer(scene.scene_id, layer_id)
        assert viewer.setPaintTarget(scene.scene_id, layer_id)
        assert viewer.setCloneStampSource(QPointF(80.0, 128.0))
        viewer.setControlMode(viewer.CONTROL_MODE_CLONE_STAMP)
        before = viewer.editableRasterLayerImage(scene.scene_id, layer_id)
        painting = viewer.paintingCoordinator()

        assert before is not None
        assert painting.begin()
        assert painting.apply(
            BrushStrokeSegment.fixed(
                (320.0, 128.0),
                (390.0, 128.0),
                48.0,
                False,
            )
        )
        assert viewer.removeLayer(scene.scene_id, layer_id)
        assert all(layer.layer_id != layer_id for layer in viewer.currentScene().layers)

        assert viewer.undoSceneEdit()
        restored_scene = viewer.currentScene()
        assert restored_scene is not None
        restored = viewer.editableRasterLayerImage(
            restored_scene.scene_id,
            layer_id,
        )
        assert restored == before
        assert viewer.undoSceneEdit()
        assert all(layer.layer_id != layer_id for layer in viewer.currentScene().layers)
        assert not viewer.sceneEditUndoAvailable()
    finally:
        viewer.close()
        viewer.deleteLater()
        qapp.processEvents()


def test_tool_and_composition_switches_abandon_unfinished_clone_strokes(
    qapp: QApplication,
) -> None:
    """Context changes must cancel transient clone pixels and retain no edit."""
    viewer = CuteCanvas()
    try:
        first_composition = viewer.createComposition(QRectF(0.0, 0.0, 512.0, 256.0))
        layer_id = viewer.addEditableRasterLayer(
            _source_band(QSize(512, 256), split=220),
            interaction=LayerPolicy(selectable=True, pixel_editable=True),
            label="Switch-safe clone target",
        )
        first_scene = viewer.currentScene()
        assert first_scene is not None and layer_id is not None
        assert viewer.setSelectedLayer(first_scene.scene_id, layer_id)
        assert viewer.setPaintTarget(first_scene.scene_id, layer_id)
        assert viewer.setCloneStampSource(QPointF(80.0, 128.0))
        assert viewer.setCloneStampTransform(
            CloneStampTransform(
                rotation_degrees=33.0,
                scale_x=1.4,
                scale_y=0.7,
                mirror_vertical=True,
            )
        )
        viewer.setControlMode(viewer.CONTROL_MODE_CLONE_STAMP)
        before = viewer.editableRasterLayerImage(first_scene.scene_id, layer_id)
        painting = viewer.paintingCoordinator()

        assert before is not None
        assert painting.begin()
        assert painting.apply(
            BrushStrokeSegment.fixed(
                (320.0, 128.0),
                (390.0, 128.0),
                48.0,
                False,
            )
        )
        viewer.setControlMode(viewer.CONTROL_MODE_PANZOOM)
        assert viewer.editableRasterLayerImage(first_scene.scene_id, layer_id) == before
        assert viewer.cloneStampOperation().source_scene_point() == QPointF(80.0, 128.0)
        assert not painting.commit()

        viewer.setControlMode(viewer.CONTROL_MODE_CLONE_STAMP)
        assert painting.begin()
        assert painting.apply(
            BrushStrokeSegment.fixed(
                (320.0, 128.0),
                (390.0, 128.0),
                48.0,
                False,
            )
        )
        viewer.createComposition(QRectF(0.0, 0.0, 128.0, 128.0))
        viewer.openComposition(first_composition)
        reopened = viewer.currentScene()
        assert reopened is not None
        assert viewer.editableRasterLayerImage(reopened.scene_id, layer_id) == before
        assert not painting.commit()
    finally:
        viewer.close()
        viewer.deleteLater()
        qapp.processEvents()


def _source_band(size: QSize, *, split: int) -> QImage:
    """Return premultiplied source color followed by transparent destination space."""
    image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.fillRect(
        QRect(0, 0, min(split, size.width()), size.height()),
        QColor(35, 125, 235, 255),
    )
    painter.end()
    return image


def _wait_for_raster_bounds(
    harness: MountedQPaneHarness,
    scene_id: uuid.UUID,
    layer_id: uuid.UUID,
    bounds: QRect,
) -> None:
    """Apply raster bounds and wait for the matching asynchronous completion."""
    completions: list[tuple[object, ...]] = []
    harness.viewer.rasterBoundsRequestCompleted.connect(
        lambda *values: completions.append(tuple(values))
    )
    request_id = harness.viewer.requestRasterBounds(scene_id, layer_id, bounds)
    assert request_id is not None
    deadline = interaction_clock() + 3.0
    while interaction_clock() < deadline:
        harness.drain_events(wait_ms=1)
        matching = [
            completion
            for completion in completions
            if completion and completion[0] == request_id
        ]
        if matching:
            assert matching[-1][3] is True
            return
    raise AssertionError("raster bounds request did not complete")
