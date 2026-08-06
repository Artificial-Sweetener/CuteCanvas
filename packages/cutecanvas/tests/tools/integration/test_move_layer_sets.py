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

"""Mounted correctness and abuse proof for Move-tool layer sets."""

from __future__ import annotations

import numpy as np
import pytest
from cutecanvas import LayerPolicy, MoveToolOptions
from cutecanvas_test_support.harness.mounted_qpane import MountedQPaneHarness
from cutecanvas_test_support.harness.timing import (
    interaction_clock,
    stable_latency_samples,
)
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from qpane.raster.image_conversion import qimage_to_numpy_argb32


def _paint_square(layer: object, left: int, top: int, size: int) -> None:
    """Replace a real mask with one opaque square."""

    def mutate(pixels: np.ndarray, _image: object) -> None:
        """Write deterministic occupied coverage."""
        pixels.fill(0)
        pixels[top : top + size, left : left + size] = 255

    layer.coverage.raster.mutate(mutate)


def _panel_point(viewer: object, scene_point: QPointF):
    """Return an integer panel point for one visible scene position."""
    panel_point = viewer.view().scene_to_panel_point(scene_point)
    assert panel_point is not None
    return panel_point.toPoint()


def _prepare_two_layer_harness(qapp) -> tuple[MountedQPaneHarness, object, object]:
    """Return a mounted editor with two disjoint movable mask layers."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(800, 600),
        widget_size=QSize(1000, 760),
        mask_count=2,
    )
    viewer = harness.viewer
    first_id, second_id = harness.mask_ids
    first_asset = viewer.mask_service.assets.get_layer(first_id)
    second_asset = viewer.mask_service.assets.get_layer(second_id)
    assert first_asset is not None and second_asset is not None
    _paint_square(first_asset, 100, 100, 80)
    _paint_square(second_asset, 300, 100, 80)
    viewer.invalidateActiveMaskCache()
    viewer.markDirty()
    viewer.update()
    assert harness.wait_for_mask_render_idle()
    entries = {entry.mask_id: entry for entry in viewer.listMasksForComposition()}
    first = entries[first_id]
    second = entries[second_id]
    assert first.scene_id is not None and first.layer_id is not None
    assert second.scene_id == first.scene_id and second.layer_id is not None
    policy = LayerPolicy(selectable=True, movable=True, pixel_editable=True)
    viewer.setLayerInteractionPolicy(first.scene_id, first.layer_id, policy)
    viewer.setLayerInteractionPolicy(second.scene_id, second.layer_id, policy)
    viewer.setControlMode(viewer.CONTROL_MODE_MOVE)
    harness.drain_events()
    return harness, first, second


def test_shift_selection_and_drag_move_one_atomic_layer_set(qapp) -> None:
    """Additive canvas selection should move and undo every member together."""
    harness, first, second = _prepare_two_layer_harness(qapp)
    viewer = harness.viewer
    try:
        viewer.setSelectedLayer(first.scene_id, first.layer_id)
        assert viewer.selectedLayer().layer_id == first.layer_id
        second_point = _panel_point(viewer, QPointF(340.0, 140.0))
        QTest.mouseClick(
            viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ShiftModifier,
            second_point,
        )
        harness.drain_events()
        assert tuple(item.layer_id for item in viewer.selectedLayers()) == (
            first.layer_id,
            second.layer_id,
        )
        assert viewer.selectedLayer().layer_id == second.layer_id

        start = _panel_point(viewer, QPointF(140.0, 140.0))
        end = _panel_point(viewer, QPointF(190.0, 175.0))
        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(viewer, end, delay=0)
        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=end)
        harness.drain_events()

        for layer_id in (first.layer_id, second.layer_id):
            transform = viewer.layerTransform(first.scene_id, layer_id)
            assert transform is not None
            assert (transform.dx(), transform.dy()) == pytest.approx(
                (50.0, 35.0),
                abs=0.6,
            )
        assert viewer.undoSceneEdit()
        harness.drain_events()
        for layer_id in (first.layer_id, second.layer_id):
            transform = viewer.layerTransform(first.scene_id, layer_id)
            assert transform is not None
            assert (transform.dx(), transform.dy()) == (0.0, 0.0)
    finally:
        harness.close()


def test_disabled_auto_selection_moves_existing_set_from_another_layer(qapp) -> None:
    """Disabled auto-selection must not replace the selected layer under press."""
    harness, first, second = _prepare_two_layer_harness(qapp)
    viewer = harness.viewer
    try:
        viewer.setSelectedLayer(first.scene_id, first.layer_id)
        assert viewer.selectedLayer().layer_id == first.layer_id
        assert viewer.setMoveToolOptions(MoveToolOptions(auto_select_layers=False))
        start = _panel_point(viewer, QPointF(340.0, 140.0))
        end = _panel_point(viewer, QPointF(380.0, 140.0))
        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(viewer, end, delay=0)
        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=end)
        harness.drain_events()

        assert viewer.selectedLayer().layer_id == first.layer_id
        first_transform = viewer.layerTransform(first.scene_id, first.layer_id)
        second_transform = viewer.layerTransform(second.scene_id, second.layer_id)
        assert first_transform is not None and second_transform is not None
        assert first_transform.dx() == pytest.approx(40.0, abs=0.6)
        assert second_transform.dx() == 0.0

        assert viewer.undoSceneEdit()
        assert viewer.setMoveToolOptions(MoveToolOptions(auto_select_layers=True))
        QTest.mousePress(
            viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ControlModifier,
            start,
        )
        QTest.mouseMove(viewer, end, delay=0)
        QTest.mouseRelease(
            viewer,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ControlModifier,
            end,
        )
        harness.drain_events()
        assert viewer.selectedLayer().layer_id == first.layer_id
        first_transform = viewer.layerTransform(first.scene_id, first.layer_id)
        second_transform = viewer.layerTransform(second.scene_id, second.layer_id)
        assert first_transform is not None and second_transform is not None
        assert first_transform.dx() == pytest.approx(40.0, abs=0.6)
        assert second_transform.dx() == 0.0
    finally:
        harness.close()


def test_multi_layer_preview_and_settled_commit_render_identically(qapp) -> None:
    """A layer-set commit must not expose a distinct presentation frame."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(800, 600),
        widget_size=QSize(1000, 760),
    )
    viewer = harness.viewer
    try:
        first_image = QImage(80, 80, QImage.Format.Format_ARGB32_Premultiplied)
        first_image.fill(QColor("red"))
        second_image = QImage(80, 80, QImage.Format.Format_ARGB32_Premultiplied)
        second_image.fill(QColor("blue"))
        first_id = viewer.addEditableRasterLayer(
            first_image,
            placement=QRectF(100.0, 100.0, 80.0, 80.0),
        )
        second_id = viewer.addEditableRasterLayer(
            second_image,
            placement=QRectF(300.0, 100.0, 80.0, 80.0),
        )
        scene = viewer.currentScene()
        assert scene is not None and first_id is not None and second_id is not None
        assert viewer.setSelectedLayers(
            scene.scene_id,
            (first_id, second_id),
            active_layer_id=second_id,
        )
        assert viewer.configureSnapping(enabled=False)
        start = _panel_point(viewer, QPointF(140.0, 140.0))
        end = _panel_point(viewer, QPointF(190.0, 170.0))
        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(viewer, end, delay=0)
        harness.drain_events()
        preview_scene = viewer.view().current_scene_descriptor()
        assert preview_scene is not None
        preview_placements = {
            layer.layer_id: layer.placement for layer in preview_scene.layers
        }
        preview = qimage_to_numpy_argb32(harness.capture()).copy()

        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=end)
        harness.drain_events()
        assert harness.wait_for_render_refinement_idle()
        settled = qimage_to_numpy_argb32(harness.capture()).copy()
        settled_scene = viewer.view().current_scene_descriptor()
        assert settled_scene is not None
        settled_placements = {
            layer.layer_id: layer.placement for layer in settled_scene.layers
        }
        assert preview_placements[first_id] == settled_placements[first_id]
        assert preview_placements[second_id] == settled_placements[second_id]

        changed = np.any(preview != settled, axis=2)
        assert not np.any(changed), int(np.count_nonzero(changed))
    finally:
        harness.close()


@pytest.mark.interactive_performance
def test_multi_layer_preview_stays_bounded_under_reversal_storm(qapp) -> None:
    """Rapid group reversals must keep one bounded preview set and pointer cost."""
    harness, first, second = _prepare_two_layer_harness(qapp)
    viewer = harness.viewer
    try:
        assert viewer.setSelectedLayers(
            first.scene_id,
            (first.layer_id, second.layer_id),
            active_layer_id=second.layer_id,
        )
        start = _panel_point(viewer, QPointF(140.0, 140.0))
        left = _panel_point(viewer, QPointF(120.0, 130.0))
        right = _panel_point(viewer, QPointF(180.0, 160.0))
        QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=start)
        latencies_ms: list[float] = []
        for index in range(300):
            started = interaction_clock()
            QTest.mouseMove(viewer, right if index % 2 else left, delay=0)
            harness.drain_events()
            latencies_ms.append((interaction_clock() - started) * 1000.0)
            assert len(viewer._scene_transform_preview.previews) == 2
        QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=right)
        harness.drain_events()
        assert not viewer._scene_transform_preview.previews
        assert max(stable_latency_samples(latencies_ms)) < 32.0, latencies_ms
    finally:
        harness.close()
