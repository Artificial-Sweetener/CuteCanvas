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
"""Regression proof for affine rotation of editable mask coverage."""

from __future__ import annotations

import math
from collections import deque
from itertools import pairwise

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QTransform
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cutecanvas import (
    BrushPreset,
    EditorTransformCommand,
    EditorTransformTarget,
    LayerPolicy,
)
from cutecanvas.editor.transform_interaction import TransformBoxPresentation
from cutecanvas_test_support.harness.mounted_qpane import MountedQPaneHarness
from qpane.sdk.raster import qimage_to_numpy_argb32, qimage_to_numpy_grayscale8


def test_selection_rotation_preserves_mask_coverage_and_undo(
    qapp: QApplication,
) -> None:
    """Rotating selected mask pixels must neither clip nor erase their coverage."""

    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(96, 96),
        widget_size=QSize(320, 320),
        mask_count=1,
        cache_budget_mb=32,
    )
    viewer = harness.viewer
    mask_id = harness.mask_ids[0]
    info = viewer.listMasksForComposition()[0]
    try:
        assert info.scene_id is not None and info.layer_id is not None
        source = QImage(96, 96, QImage.Format_Grayscale8)
        source.fill(0)
        for y in range(43, 51):
            for x in range(39, 57):
                source.setPixel(x, y, 255)
        for y in range(44, 50):
            for x in range(41, 45):
                source.setPixel(x, y, 128)
        for y in range(45, 49):
            for x in range(48, 54):
                source.setPixel(x, y, 0)
        assert viewer.replaceMaskImage(mask_id, source)
        info = viewer.listMasksForComposition()[0]
        assert info.scene_id is not None and info.layer_id is not None
        viewer.setLayerInteractionPolicy(
            info.scene_id,
            info.layer_id,
            LayerPolicy(selectable=True, movable=True, pixel_editable=True),
        )
        viewer.setSelectedLayer(info.scene_id, info.layer_id)
        selected = viewer.selectedLayer()
        assert selected is not None and selected.layer_id == info.layer_id
        assert harness.wait_for_mask_render_idle()
        before = viewer.exportMaskImage(mask_id)
        assert before is not None

        selection = QImage(28, 20, QImage.Format_Grayscale8)
        selection.fill(255)
        assert viewer.setPixelSelection(selection, QRect(34, 37, 28, 20))
        assert viewer.activateEditorTransform(EditorTransformTarget.SELECTION_CONTENT)
        assert viewer.applyEditorTransformCommand(
            EditorTransformCommand.ROTATE_RIGHT_90
        )
        assert viewer.applyEditorTransform()
        harness.drain_events()

        rotated = viewer.exportMaskImage(mask_id)
        assert rotated is not None
        before_pixels = qimage_to_numpy_grayscale8(before)
        rotated_pixels = qimage_to_numpy_grayscale8(rotated)
        assert np.count_nonzero(rotated_pixels) == np.count_nonzero(before_pixels)
        assert int(rotated_pixels.sum()) == int(before_pixels.sum())
        rotated_rows, rotated_columns = np.nonzero(rotated_pixels)
        assert rotated_columns.max() - rotated_columns.min() + 1 == 8
        assert rotated_rows.max() - rotated_rows.min() + 1 == 18

        assert viewer.undoSceneEdit()
        restored = viewer.exportMaskImage(mask_id)
        assert restored is not None
        np.testing.assert_array_equal(
            qimage_to_numpy_grayscale8(restored),
            before_pixels,
        )

        assert viewer.activateEditorTransform(EditorTransformTarget.SELECTION_CONTENT)
        presentation = viewer.sceneLayerTransformInteraction().presentation()
        assert presentation is not None
        rotate_start, rotate_finish = _rotation_drag(presentation, 37.0)
        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=rotate_start)
        QTest.mouseMove(viewer, rotate_finish, delay=0)
        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=rotate_finish)
        assert viewer.applyEditorTransform()
        harness.drain_events()

        freely_rotated = viewer.exportMaskImage(mask_id)
        assert freely_rotated is not None
        freely_rotated_pixels = qimage_to_numpy_grayscale8(freely_rotated)
        assert np.count_nonzero(freely_rotated_pixels) > 0
        assert int(freely_rotated_pixels.sum()) >= int(before_pixels.sum()) * 0.9
        assert int(freely_rotated_pixels.sum()) <= int(before_pixels.sum()) * 1.1

        assert viewer.undoSceneEdit()
        transformed_layer = QTransform(0.75, 0.0, 0.0, 0.75, 10.0, 8.0)
        assert viewer.setLayerTransform(
            info.scene_id,
            info.layer_id,
            transformed_layer,
        )
        transformed_before = viewer.exportMaskImage(mask_id)
        assert transformed_before is not None
        transformed_before_pixels = qimage_to_numpy_grayscale8(transformed_before)
        transformed_selection = QImage(24, 18, QImage.Format_Grayscale8)
        transformed_selection.fill(255)
        assert viewer.setPixelSelection(
            transformed_selection,
            QRect(34, 34, 24, 18),
        )
        assert viewer.activateEditorTransform(EditorTransformTarget.SELECTION_CONTENT)
        assert viewer.applyEditorTransformCommand(
            EditorTransformCommand.ROTATE_RIGHT_90
        )
        assert viewer.applyEditorTransform()
        harness.drain_events()

        transformed_rotation = viewer.exportMaskImage(mask_id)
        assert transformed_rotation is not None
        transformed_pixels = qimage_to_numpy_grayscale8(transformed_rotation)
        assert np.count_nonzero(transformed_pixels) > 0
        assert (
            int(transformed_pixels.sum()) >= int(transformed_before_pixels.sum()) * 0.85
        )
        assert (
            int(transformed_pixels.sum()) <= int(transformed_before_pixels.sum()) * 1.15
        )
    finally:
        harness.close()


def test_selection_rotation_preserves_content_beneath_transparent_corners(
    qapp: QApplication,
) -> None:
    """Rotated transparent selection storage must not erase stationary coverage."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(64, 64),
        widget_size=QSize(256, 256),
        mask_count=1,
        cache_budget_mb=32,
    )
    viewer = harness.viewer
    mask_id = harness.mask_ids[0]
    info = viewer.listMasksForComposition()[0]
    try:
        assert info.scene_id is not None and info.layer_id is not None
        source = QImage(64, 64, QImage.Format_Grayscale8)
        source.fill(0)
        source.setPixel(20, 20, 255)
        source.setPixel(29, 23, 255)
        source.setPixelColor(25, 18, QColor(180, 180, 180))
        assert viewer.replaceMaskImage(mask_id, source)
        viewer.setLayerInteractionPolicy(
            info.scene_id,
            info.layer_id,
            LayerPolicy(selectable=True, movable=True, pixel_editable=True),
        )
        viewer.setSelectedLayer(info.scene_id, info.layer_id)
        selection = QImage(10, 4, QImage.Format_Grayscale8)
        selection.fill(255)
        assert viewer.setPixelSelection(selection, QRect(20, 20, 10, 4))
        assert viewer.activateEditorTransform(EditorTransformTarget.SELECTION_CONTENT)
        assert viewer.applyEditorTransformCommand(
            EditorTransformCommand.ROTATE_RIGHT_90
        )
        assert viewer.applyEditorTransform()

        rotated = viewer.exportMaskImage(mask_id)
        assert rotated is not None
        rotated_pixels = qimage_to_numpy_grayscale8(rotated)
        assert rotated_pixels[18, 25] == 180
        assert np.count_nonzero(rotated_pixels) == 3
    finally:
        harness.close()


def test_connected_acute_mask_arc_remains_complete_during_rotation_preview(
    qapp: QApplication,
) -> None:
    """A rotated nonuniform mask must stay connected before and after settlement."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(512, 512),
        widget_size=QSize(512, 512),
        mask_count=1,
        cache_budget_mb=32,
    )
    viewer = harness.viewer
    mask_id = harness.mask_ids[0]
    info = viewer.listMasksForComposition()[0]
    try:
        assert info.scene_id is not None and info.layer_id is not None
        layer = viewer.mask_service.assets.get_layer(mask_id)
        assert layer is not None
        assert layer.coverage.compact_raster_storage()
        assert layer.coverage.raster.is_null()
        assert viewer.setLayerTransform(
            info.scene_id,
            info.layer_id,
            QTransform(2.0, 0.0, 0.0, 0.5, -256.0, 128.0),
        )
        viewer.setBrushPreset(BrushPreset(size=18.0, hardness=1.0, spacing=0.15))
        viewer.setControlMode(viewer.CONTROL_MODE_DRAW_BRUSH)
        scene_points = (
            QPointF(60.0, 330.0),
            QPointF(256.0, 160.0),
            QPointF(450.0, 330.0),
        )
        panel_points: list[QPoint] = []
        for first, second in pairwise(scene_points):
            for step in range(65):
                progress = step / 64.0
                point = first + (second - first) * progress
                panel_rect = viewer.sceneToPanelRect(
                    QRectF(point.x(), point.y(), 1.0, 1.0)
                )
                assert panel_rect is not None
                panel_point = panel_rect.center().toPoint()
                if not panel_points or panel_points[-1] != panel_point:
                    panel_points.append(panel_point)
        QTest.mousePress(viewer, Qt.LeftButton, Qt.NoModifier, panel_points[0])
        for point in panel_points[1:]:
            QTest.mouseMove(viewer, point, delay=0)
        QTest.mouseRelease(
            viewer,
            Qt.LeftButton,
            Qt.NoModifier,
            panel_points[-1],
        )
        assert harness.wait_for_mask_undo_depth(mask_id, 1)
        assert harness.wait_for_mask_render_idle()
        source = viewer.exportMaskImage(mask_id)
        assert source is not None
        source_pixels = qimage_to_numpy_grayscale8(source)
        stored_before = layer.coverage.snapshot_array()
        assert _connected_component_sizes(source_pixels > 127) == [
            int(np.count_nonzero(source_pixels > 127))
        ]
        viewer.setLayerInteractionPolicy(
            info.scene_id,
            info.layer_id,
            LayerPolicy(selectable=True, movable=True, pixel_editable=True),
        )
        viewer.setSelectedLayer(info.scene_id, info.layer_id)
        assert viewer.activateEditorTransform(EditorTransformTarget.LAYER_CONTENT)
        assert harness.wait_for_mask_render_idle()

        presentation = viewer.sceneLayerTransformInteraction().presentation()
        assert presentation is not None
        rotate_start, rotate_finish = _rotation_drag(presentation, 41.0)
        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=rotate_start)
        QTest.mouseMove(viewer, rotate_finish, delay=0)
        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=rotate_finish)
        harness.drain_events()

        base_buffer = viewer.view().presenter.renderer.get_base_buffer()
        assert base_buffer is not None
        preview_components = _presented_mask_component_sizes(base_buffer)
        assert len(preview_components) == 1

        assert viewer.applyEditorTransform()
        harness.drain_events()
        np.testing.assert_array_equal(layer.coverage.snapshot_array(), stored_before)
        settled_buffer = viewer.view().presenter.renderer.get_base_buffer()
        assert settled_buffer is not None
        assert len(_presented_mask_component_sizes(settled_buffer)) == 1
    finally:
        harness.close()


def _rotation_drag(
    box: TransformBoxPresentation,
    angle_degrees: float,
) -> tuple[QPoint, QPoint]:
    """Return exterior start and end points rotating around a transform frame."""

    top = next(point for handle, point in box.handles if handle.value == "top")
    radial = top - box.center
    length = math.hypot(radial.x(), radial.y())
    start_vector = QPointF(
        radial.x() / length * (length + 16.0),
        radial.y() / length * (length + 16.0),
    )
    radians = math.radians(angle_degrees)
    end_vector = QPointF(
        start_vector.x() * math.cos(radians) - start_vector.y() * math.sin(radians),
        start_vector.x() * math.sin(radians) + start_vector.y() * math.cos(radians),
    )
    return (box.center + start_vector).toPoint(), (box.center + end_vector).toPoint()


def _presented_mask_component_sizes(image: QImage) -> list[int]:
    """Return connected opaque pink-mask component sizes from one backing frame."""
    pixels = qimage_to_numpy_argb32(image)
    mask = (
        (pixels[:, :, 2] >= 245)
        & (pixels[:, :, 1] >= 120)
        & (pixels[:, :, 1] <= 220)
        & (np.abs(pixels[:, :, 0].astype(int) - pixels[:, :, 1].astype(int)) <= 2)
    )
    return _connected_component_sizes(mask)


def _connected_component_sizes(mask: np.ndarray) -> list[int]:
    """Return descending 8-connected component sizes for a binary oracle image."""
    seen = np.zeros(mask.shape, dtype=np.bool_)
    sizes: list[int] = []
    height, width = mask.shape
    for row, column in zip(*np.nonzero(mask), strict=True):
        if seen[row, column]:
            continue
        pending = deque(((int(row), int(column)),))
        seen[row, column] = True
        size = 0
        while pending:
            current_row, current_column = pending.pop()
            size += 1
            for row_offset in (-1, 0, 1):
                for column_offset in (-1, 0, 1):
                    if row_offset == 0 and column_offset == 0:
                        continue
                    neighbor_row = current_row + row_offset
                    neighbor_column = current_column + column_offset
                    if (
                        0 <= neighbor_row < height
                        and 0 <= neighbor_column < width
                        and mask[neighbor_row, neighbor_column]
                        and not seen[neighbor_row, neighbor_column]
                    ):
                        seen[neighbor_row, neighbor_column] = True
                        pending.append((neighbor_row, neighbor_column))
        sizes.append(size)
    return sorted(sizes, reverse=True)
