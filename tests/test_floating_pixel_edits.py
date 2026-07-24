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
"""Mounted public-contract tests for unresolved floating pixel edits."""

from __future__ import annotations

import numpy as np
from cutecanvas import FloatingPixelMode, LayerPolicy, RasterExtentPolicy
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from .harness.mounted_qpane import MountedQPaneHarness


def _soft_rgba_payload() -> QImage:
    """Return transparent storage containing a soft premultiplied color payload."""
    image = QImage(64, 64, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.fillRect(QRect(16, 16, 32, 32), QColor(30, 120, 220, 128))
    painter.end()
    return image


def test_mask_fragment_release_promote_and_history_are_atomic(
    qapp: QApplication,
) -> None:
    """Release must stay transient; promotion and replay must span both layers."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(256, 256),
        widget_size=QSize(512, 512),
        mask_count=1,
    )
    viewer = harness.viewer
    source_mask_id = harness.mask_ids[0]
    info = viewer.listMasksForComposition()[0]
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
        viewer.configureSnapping(enabled=False)
        source = viewer.mask_service.assets.get_layer(source_mask_id)
        assert source is not None

        def paint_square(pixels: np.ndarray, _image: QImage) -> None:
            """Paint a bounded payload with empty surrounding storage."""
            pixels[60:100, 60:100] = 255

        source.coverage.raster.mutate(paint_square)
        viewer.invalidateActiveMaskCache()
        viewer.markDirty()
        viewer.update()
        selection = QImage(40, 40, QImage.Format_Grayscale8)
        selection.fill(255)
        assert viewer.setPixelSelection(selection, QRect(60, 60, 40, 40))
        coordinates = viewer.activeMaskLayerCoordinates()
        start = coordinates.source_to_panel(QPoint(80, 80))
        finish = coordinates.source_to_panel(QPoint(130, 110))
        assert start is not None
        assert finish is not None
        states: list[object] = []
        viewer.floatingPixelEditChanged.connect(states.append)
        viewer.setControlMode(viewer.CONTROL_MODE_MOVE)

        QTest.mousePress(viewer, Qt.LeftButton, Qt.NoModifier, start.toPoint())
        QTest.mouseMove(viewer, finish.toPoint(), delay=0)
        QTest.mouseRelease(viewer, Qt.LeftButton, Qt.NoModifier, finish.toPoint())
        harness.drain_events()

        floating = viewer.floatingPixelEditState()
        assert floating is not None
        assert floating.mode is FloatingPixelMode.CUT
        assert floating.source_layer_id == info.layer_id
        assert floating.offset == QPoint(50, 30)
        assert source.coverage.raster.storage_value(60, 60) == 255
        assert states and states[-1] == floating

        promoted_layer_id = viewer.promoteFloatingPixels("Detached mask")

        assert promoted_layer_id is not None
        assert viewer.floatingPixelEditState() is None
        assert source.coverage.raster.storage_value(60, 60) == 0
        masks = viewer.listMasksForComposition()
        promoted = next(item for item in masks if item.layer_id == promoted_layer_id)
        promoted_source = viewer.mask_service.assets.get_layer(promoted.mask_id)
        assert promoted_source is not None
        assert promoted_source.coverage.raster.bounds.to_qrect() == QRect(
            60, 60, 40, 40
        )
        assert promoted_source.coverage.raster.storage_value(0, 0) == 255
        assert viewer.selectedLayer().layer_id == promoted_layer_id

        assert viewer.undoSceneEdit()
        assert source.coverage.raster.storage_value(60, 60) == 255
        assert all(
            item.layer_id != promoted_layer_id
            for item in viewer.listMasksForComposition()
        )
        assert viewer.selectedLayer().layer_id == info.layer_id

        assert viewer.redoSceneEdit()
        assert source.coverage.raster.storage_value(60, 60) == 0
        assert any(
            item.layer_id == promoted_layer_id
            for item in viewer.listMasksForComposition()
        )
        assert viewer.selectedLayer().layer_id == promoted_layer_id
    finally:
        harness.close()


def test_escape_cancels_floating_cut_without_history_or_pixel_changes(
    qapp: QApplication,
) -> None:
    """Cancellation must restore the exact pre-lift state without a history edit."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(256, 256),
        widget_size=QSize(512, 512),
        mask_count=1,
    )
    viewer = harness.viewer
    info = viewer.listMasksForComposition()[0]
    source = viewer.mask_service.assets.get_layer(harness.mask_ids[0])
    try:
        assert source is not None
        assert info.scene_id is not None
        assert info.layer_id is not None
        viewer.setLayerInteractionPolicy(
            info.scene_id,
            info.layer_id,
            LayerPolicy(selectable=True, pixel_editable=True),
        )
        viewer.setSelectedLayer(info.scene_id, info.layer_id)
        assert viewer.selectedLayer().layer_id == info.layer_id

        def paint_square(pixels: np.ndarray, _image: QImage) -> None:
            """Paint only the selected payload for exact replay assertions."""
            pixels[40:72, 40:72] = 255

        source.coverage.raster.mutate(paint_square)
        before = source.coverage.raster.snapshot_array()
        selection = QImage(32, 32, QImage.Format_Grayscale8)
        selection.fill(255)
        assert viewer.setPixelSelection(selection, QRect(40, 40, 32, 32))
        start = viewer.activeMaskLayerCoordinates().source_to_panel(QPoint(50, 50))
        finish = viewer.activeMaskLayerCoordinates().source_to_panel(QPoint(100, 90))
        assert start is not None
        assert finish is not None
        viewer.setControlMode(viewer.CONTROL_MODE_MOVE)
        viewer.setFocus(Qt.FocusReason.OtherFocusReason)
        QTest.mousePress(viewer, Qt.LeftButton, Qt.NoModifier, start.toPoint())
        QTest.mouseMove(viewer, finish.toPoint(), delay=0)
        QTest.mouseRelease(viewer, Qt.LeftButton, Qt.NoModifier, finish.toPoint())
        assert viewer.floatingPixelEditState() is not None

        QTest.keyClick(viewer, Qt.Key_Escape)

        assert viewer.floatingPixelEditState() is None
        np.testing.assert_array_equal(source.coverage.raster.snapshot_array(), before)
        selection_state = viewer.pixelSelectionState()
        assert selection_state is not None
        assert selection_state.bounds == QRect(40, 40, 32, 32)

        QTest.mousePress(viewer, Qt.LeftButton, Qt.NoModifier, start.toPoint())
        QTest.mouseMove(viewer, finish.toPoint(), delay=0)
        QTest.mouseRelease(viewer, Qt.LeftButton, Qt.NoModifier, finish.toPoint())
        assert viewer.floatingPixelEditState() is not None
        assert viewer.undoSceneEdit()
        assert viewer.floatingPixelEditState() is None
        np.testing.assert_array_equal(source.coverage.raster.snapshot_array(), before)
        assert viewer.sceneEditRedoAvailable()
        assert viewer.redoSceneEdit()
        assert source.coverage.raster.storage_value(40, 40) == 0
        assert source.coverage.raster.storage_value(90, 80) == 255
    finally:
        harness.close()


def test_rgba_fragment_promotes_as_real_rendered_layer_with_atomic_history(
    qapp: QApplication,
) -> None:
    """RGBA promotion must preserve soft pixels and use normal layer lifecycle."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(256, 256),
        widget_size=QSize(512, 512),
        mask_count=1,
    )
    viewer = harness.viewer
    scene = viewer.currentScene()
    assert scene is not None
    source_layer_id = viewer.addEditableRasterLayer(
        _soft_rgba_payload(),
        placement=QRectF(0.0, 0.0, 64.0, 64.0),
        label="Paint",
    )
    try:
        assert source_layer_id is not None
        harness.drain_events()
        assert viewer.setSelectedLayer(scene.scene_id, source_layer_id)
        selection = QImage(48, 48, QImage.Format_Grayscale8)
        selection.fill(255)
        assert viewer.setPixelSelection(selection, QRect(8, 8, 48, 48))
        resolved_scene_id = viewer._resolve_public_scene_id(scene.scene_id)
        start = viewer.view().layer_source_to_panel_point(
            resolved_scene_id,
            source_layer_id,
            QPoint(24, 24),
        )
        finish = viewer.view().layer_source_to_panel_point(
            resolved_scene_id,
            source_layer_id,
            QPoint(44, 36),
        )
        assert start is not None
        assert finish is not None
        viewer.setControlMode(viewer.CONTROL_MODE_MOVE)

        QTest.keyPress(viewer, Qt.Key_Control)
        QTest.mousePress(viewer, Qt.LeftButton, Qt.ControlModifier, start.toPoint())
        QTest.mouseMove(viewer, finish.toPoint(), delay=0)
        QTest.mouseRelease(
            viewer,
            Qt.LeftButton,
            Qt.ControlModifier,
            finish.toPoint(),
        )
        QTest.keyRelease(viewer, Qt.Key_Control)
        harness.drain_events()

        floating = viewer.floatingPixelEditState()
        assert floating is not None
        assert floating.bounds == QRect(36, 28, 32, 32)
        source_before = viewer.editableRasterLayerImage(
            scene.scene_id,
            source_layer_id,
        )
        assert source_before is not None
        assert source_before.pixelColor(20, 20).alpha() == 128

        promoted_layer_id = viewer.promoteFloatingPixels("Detached paint")

        assert promoted_layer_id is not None
        source_after = viewer.editableRasterLayerImage(
            scene.scene_id,
            source_layer_id,
        )
        promoted = viewer.editableRasterLayerImage(
            scene.scene_id,
            promoted_layer_id,
        )
        assert source_after is not None
        assert promoted is not None
        assert source_after.pixelColor(20, 20).alpha() == 0
        assert promoted.size() == QSize(32, 32)
        assert promoted.pixelColor(4, 4) == source_before.pixelColor(20, 20)
        plan = viewer.view().calculateRenderPlan(is_blank=False)
        assert plan is not None
        assert any(
            item.descriptor.layer_id == promoted_layer_id for item in plan.render_items
        )

        assert viewer.undoSceneEdit()
        restored = viewer.editableRasterLayerImage(scene.scene_id, source_layer_id)
        assert restored == source_before
        assert (
            viewer.editableRasterLayerImage(scene.scene_id, promoted_layer_id) is None
        )

        assert viewer.redoSceneEdit()
        assert (
            viewer.editableRasterLayerImage(scene.scene_id, promoted_layer_id)
            == promoted
        )
        redone_source = viewer.editableRasterLayerImage(
            scene.scene_id,
            source_layer_id,
        )
        assert redone_source is not None
        assert redone_source.pixelColor(20, 20).alpha() == 0
    finally:
        harness.close()


def test_affine_rgba_fragment_promotes_without_flattening_transform(
    qapp: QApplication,
) -> None:
    """New-layer resolution must preserve the same affine preview and chronology."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(256, 256),
        widget_size=QSize(512, 512),
        mask_count=1,
    )
    viewer = harness.viewer
    scene = viewer.currentScene()
    assert scene is not None
    source_layer_id = viewer.addEditableRasterLayer(
        _soft_rgba_payload(),
        placement=QRectF(0.0, 0.0, 64.0, 64.0),
        label="Affine paint",
    )
    try:
        assert source_layer_id is not None
        assert viewer.setSelectedLayer(scene.scene_id, source_layer_id)
        selection = QImage(32, 32, QImage.Format_Grayscale8)
        selection.fill(255)
        assert viewer.setPixelSelection(selection, QRect(16, 16, 32, 32))
        viewer.setControlMode(viewer.CONTROL_MODE_TRANSFORM)
        harness.drain_events()
        interaction = viewer.sceneLayerTransformInteraction()
        box = interaction.presentation()
        assert box is not None
        start = next(
            point for handle, point in box.handles if handle.value == "bottom-right"
        ).toPoint()
        finish = start + QPoint(64, 32)

        QTest.mousePress(viewer, Qt.LeftButton, Qt.ShiftModifier, start)
        QTest.mouseMove(viewer, finish, delay=0)
        QTest.mouseRelease(viewer, Qt.LeftButton, Qt.ShiftModifier, finish)
        harness.drain_events()

        preview = viewer._selected_pixel_movement.raster_preview
        assert preview is not None
        expected = preview.fragment_transform
        floating = viewer.floatingPixelEditState()
        assert floating is not None
        expected_placement = expected.map_rect(QRectF(16.0, 16.0, 32.0, 32.0))
        assert floating.bounds == expected_placement.toAlignedRect()
        source_before = viewer.editableRasterLayerImage(
            scene.scene_id,
            source_layer_id,
        )
        assert source_before is not None

        promoted_layer_id = viewer.promoteFloatingPixels("Affine fragment")

        assert promoted_layer_id is not None
        promoted_transform = viewer.layerTransform(scene.scene_id, promoted_layer_id)
        assert promoted_transform is not None
        assert promoted_transform.map(QPointF(16.0, 16.0)) == expected.map_point(
            QPointF(16.0, 16.0)
        )
        promoted = viewer.editableRasterLayerImage(
            scene.scene_id,
            promoted_layer_id,
        )
        assert promoted is not None and promoted.size() == QSize(32, 32)
        assert viewer.undoSceneEdit()
        assert (
            viewer.editableRasterLayerImage(scene.scene_id, source_layer_id)
            == source_before
        )
        assert (
            viewer.editableRasterLayerImage(scene.scene_id, promoted_layer_id) is None
        )
        assert viewer.redoSceneEdit()
        assert (
            viewer.editableRasterLayerImage(scene.scene_id, promoted_layer_id)
            == promoted
        )
    finally:
        harness.close()


def test_floating_session_resolves_safely_across_structure_tool_and_teardown(
    qapp: QApplication,
) -> None:
    """Host mutations and context loss must never leave stale floating state."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(256, 256),
        widget_size=QSize(512, 512),
        mask_count=1,
    )
    viewer = harness.viewer
    info = viewer.listMasksForComposition()[0]
    source = viewer.mask_service.assets.get_layer(harness.mask_ids[0])
    try:
        assert source is not None
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

        def paint_pixel(pixels: np.ndarray, _image: QImage) -> None:
            """Paint a tiny asymmetric payload for exact lifecycle checks."""
            pixels[80, 80] = 255

        source.coverage.raster.mutate(paint_pixel)
        selection = QImage(8, 8, QImage.Format_Grayscale8)
        selection.fill(255)
        assert viewer.setPixelSelection(selection, QRect(80, 80, 8, 8))
        viewer.setControlMode(viewer.CONTROL_MODE_MOVE)
        viewer.setFocus(Qt.FocusReason.OtherFocusReason)

        QTest.keyClick(viewer, Qt.Key_Right)
        assert viewer.floatingPixelEditState() is not None
        assert viewer.setRasterExtentPolicy(
            info.scene_id,
            info.layer_id,
            RasterExtentPolicy.EXPAND_ON_WRITE,
        )
        assert viewer.floatingPixelEditState() is None
        assert source.coverage.raster.storage_value(80, 80) == 0
        assert source.coverage.raster.storage_value(81, 80) == 255

        QTest.keyClick(viewer, Qt.Key_Right)
        floating_before_tool_change = viewer.floatingPixelEditState()
        assert floating_before_tool_change is not None
        viewer.setControlMode(viewer.CONTROL_MODE_DRAW_BRUSH)
        assert viewer.floatingPixelEditState() == floating_before_tool_change
        assert source.coverage.raster.storage_value(81, 80) == 255
        assert source.coverage.raster.storage_value(82, 80) == 0

        viewer.setControlMode(viewer.CONTROL_MODE_MOVE)
        assert viewer.floatingPixelEditState() == floating_before_tool_change
        QTest.keyClick(viewer, Qt.Key_Escape)
        assert viewer.floatingPixelEditState() is None
        QTest.keyClick(viewer, Qt.Key_Right)
        assert viewer.floatingPixelEditState() is not None
        composition_id = viewer.currentCompositionID()
        assert composition_id is not None
        viewer.removeComposition(composition_id)
        harness.drain_events()
        assert viewer.floatingPixelEditState() is None
        assert viewer.selectedLayer() is None
        assert viewer.pixelSelectionState() is None
    finally:
        harness.close()
