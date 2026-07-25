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
"""Mounted adversarial smart-guide and snapping workflows."""

from __future__ import annotations

import uuid

import numpy as np
import pytest
from cutecanvas import LayerPolicy, VectorShapeKind, VectorStyle
from cutecanvas.coverage import (
    CoverageCombineMode,
    CoverageGeometryFactory,
    VectorCoverageItem,
)
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from qpane.raster.image_conversion import qimage_to_numpy_argb32

from tests.harness.mounted_qpane import MountedQPaneHarness
from tests.harness.timing import (
    INTERACTIVE_PERFORMANCE,
    interaction_clock,
    stable_latency_samples,
)

pytestmark = INTERACTIVE_PERFORMANCE


def _paint_square(layer: object, left: int, top: int, size: int) -> None:
    """Paint one opaque square into a real hybrid mask asset."""

    def mutate(pixels: np.ndarray, _image: object) -> None:
        """Replace raster contents with one deterministic occupied region."""
        pixels.fill(0)
        pixels[top : top + size, left : left + size] = 255

    layer.coverage.raster.mutate(mutate)


def _first_edge_pixel(
    signal: np.ndarray,
    expected_x: float,
    *,
    threshold: int = 12,
) -> int:
    """Return the first significant pixel near one expected rendered edge."""
    start = max(0, int(np.floor(expected_x)) - 4)
    stop = min(signal.shape[0], int(np.ceil(expected_x)) + 6)
    occupied = np.flatnonzero(signal[start:stop] > threshold)
    assert occupied.size, (signal[start:stop].tolist(), expected_x)
    return start + int(occupied[0])


def test_mask_layer_corner_snapping_survives_jitter_history_and_repaint_abuse(
    qapp,
) -> None:
    """Real masks should retain a stable two-axis snap through abusive input."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(1000, 800),
        widget_size=QSize(1200, 900),
        mask_count=2,
    )
    viewer = harness.viewer
    try:
        moving_mask_id, target_mask_id = harness.mask_ids
        moving_asset = viewer.mask_service.assets.get_layer(moving_mask_id)
        target_asset = viewer.mask_service.assets.get_layer(target_mask_id)
        assert moving_asset is not None and target_asset is not None
        _paint_square(moving_asset, 100, 100, 100)
        _paint_square(target_asset, 600, 400, 100)
        viewer.invalidateActiveMaskCache()
        viewer.markDirty()
        viewer.update()
        assert harness.wait_for_mask_render_idle()

        mask_entries = {
            entry.mask_id: entry for entry in viewer.listMasksForComposition()
        }
        moving_entry = mask_entries[moving_mask_id]
        target_entry = mask_entries[target_mask_id]
        assert moving_entry.scene_id is not None and moving_entry.layer_id is not None
        assert target_entry.scene_id == moving_entry.scene_id
        assert target_entry.layer_id is not None
        policy = LayerPolicy(selectable=True, movable=True, pixel_editable=True)
        viewer.setLayerInteractionPolicy(
            moving_entry.scene_id, moving_entry.layer_id, policy
        )
        viewer.setLayerInteractionPolicy(
            target_entry.scene_id, target_entry.layer_id, policy
        )
        viewer.setActiveMaskID(moving_mask_id)
        viewer.setSelectedLayer(moving_entry.scene_id, moving_entry.layer_id)
        selected = viewer.selectedLayer()
        assert selected is not None and selected.layer_id == moving_entry.layer_id
        harness.drain_events()

        coordinates = viewer.activeMaskLayerCoordinates()
        origin = coordinates.source_to_panel(QPoint(150, 150))
        assert origin is not None
        endpoints = tuple(
            coordinates.source_to_panel(QPoint(150 + dx, 150 + dy))
            for dx, dy in (
                (397, 297),
                (401, 301),
                (398, 302),
                (403, 299),
                (399, 301),
            )
        )
        assert all(endpoint is not None for endpoint in endpoints)
        viewer.setControlMode(viewer.CONTROL_MODE_MOVE)
        QTest.mousePress(
            viewer, Qt.MouseButton.LeftButton, Qt.NoModifier, origin.toPoint()
        )
        latencies_ms: list[float] = []
        for endpoint in endpoints:
            assert endpoint is not None
            started = interaction_clock()
            QTest.mouseMove(viewer, endpoint.toPoint(), delay=0)
            harness.drain_events()
            latencies_ms.append((interaction_clock() - started) * 1000.0)
            box = viewer._editor_movement_interaction._layers.transform_box_state()
            assert box is not None
            assert box.transform.dx == pytest.approx(400.0)
            assert box.transform.dy == pytest.approx(300.0)
            assert {
                guide.axis.value
                for guide in viewer._editor_movement_interaction.snap_guides
            } == {
                "x",
                "y",
            }

        final_endpoint = endpoints[-1]
        assert final_endpoint is not None
        QTest.mouseRelease(
            viewer,
            Qt.MouseButton.LeftButton,
            Qt.NoModifier,
            final_endpoint.toPoint(),
        )
        harness.drain_events()
        assert not viewer._editor_movement_interaction.snap_guides
        transform = viewer.layerTransform(moving_entry.scene_id, moving_entry.layer_id)
        assert transform is not None
        assert transform.dx() == pytest.approx(400.0)
        assert transform.dy() == pytest.approx(300.0)
        assert max(latencies_ms) < 32.0

        assert viewer.undoSceneEdit()
        harness.drain_events()
        transform = viewer.layerTransform(moving_entry.scene_id, moving_entry.layer_id)
        assert transform is not None
        assert (transform.dx(), transform.dy()) == (0.0, 0.0)
        assert viewer.redoSceneEdit()
        harness.drain_events()
        transform = viewer.layerTransform(moving_entry.scene_id, moving_entry.layer_id)
        assert transform is not None
        assert transform.dx() == pytest.approx(400.0)
        assert transform.dy() == pytest.approx(300.0)

        viewer.markDirty()
        viewer.update()
        harness.drain_events()
        assert not viewer._editor_movement_interaction.snap_guides
    finally:
        harness.close()


def test_mask_edges_snap_to_stroked_vector_painted_edges(qapp, tmp_path) -> None:
    """Fractional retained masks must align exactly to painted vector edges."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(1600, 1000),
        widget_size=QSize(1200, 800),
    )
    viewer = harness.viewer
    try:
        composition_id = viewer.createComposition(
            QRectF(0.0, 0.0, 1600.0, 1000.0),
            title="Fractional snapping",
        )
        assert composition_id is not None
        mask_rectangle = QRectF(
            287.536231884058,
            171.88405797101453,
            591.304347826087,
            507.82608695652175,
        )
        scene = viewer.currentScene()
        assert scene is not None
        vector_layer_id = viewer.createVectorLayer(label="Stroked target")
        assert vector_layer_id is not None
        assert viewer.addVectorShape(
            scene.scene_id,
            vector_layer_id,
            VectorShapeKind.RECTANGLE,
            QRectF(360.0, 260.0, 880.0, 480.0),
            VectorStyle(
                fill=QColor("white"),
                stroke=QColor("blue"),
                stroke_width=8.0,
            ),
        )
        target_bounds = viewer.layerLocalBounds(scene.scene_id, vector_layer_id)
        assert target_bounds == QRectF(356.0, 256.0, 888.0, 488.0)
        viewer.setLayerInteractionPolicy(
            scene.scene_id,
            vector_layer_id,
            LayerPolicy(selectable=False, movable=False),
        )

        mask_id = viewer.createBlankMask(QSize(1600, 1000))
        assert mask_id is not None
        assert viewer.setActiveMaskID(mask_id)
        assert viewer.paintingCoordinator().commit_coverage_item(
            VectorCoverageItem(
                uuid.uuid4(),
                CoverageGeometryFactory().rectangle(mask_rectangle),
                combine_mode=CoverageCombineMode.REPLACE,
            )
        )
        viewer.invalidateActiveMaskCache()
        viewer.markDirty()
        viewer.update()
        assert harness.wait_for_mask_render_idle()
        assert harness.wait_for_render_refinement_idle()

        active_scene = viewer.currentScene()
        assert active_scene is not None
        mask_layer = next(
            layer for layer in active_scene.layers if layer.source_id == mask_id
        )
        viewer.setLayerInteractionPolicy(
            active_scene.scene_id,
            mask_layer.layer_id,
            LayerPolicy(selectable=True, movable=True, pixel_editable=True),
        )
        viewer.setSelectedLayer(active_scene.scene_id, mask_layer.layer_id)
        assert viewer.selectedLayer().layer_id == mask_layer.layer_id
        viewer.setControlMode(viewer.CONTROL_MODE_MOVE)
        harness.drain_events()
        moving_bounds = viewer.layerLocalBounds(
            active_scene.scene_id,
            mask_layer.layer_id,
        )
        assert moving_bounds == mask_rectangle
        expected_dx = target_bounds.left() - moving_bounds.left()
        expected_dy = target_bounds.bottom() - moving_bounds.bottom()
        coordinates = viewer.activeMaskLayerCoordinates()
        origin_source = QPointF(300.0, 200.0)
        origin = coordinates.source_to_panel(origin_source)
        endpoint = coordinates.source_to_panel(
            origin_source + QPointF(expected_dx + 0.5, expected_dy - 0.5)
        )
        jittered_endpoints = tuple(
            coordinates.source_to_panel(
                origin_source
                + QPointF(
                    expected_dx + 0.5 + (index % 7 - 3) * 0.25,
                    expected_dy - 0.5 + ((index * 5) % 7 - 3) * 0.25,
                )
            )
            for index in range(48)
        )
        assert origin is not None and endpoint is not None
        assert all(point is not None for point in jittered_endpoints)
        hit = viewer.view().scene_selection_hit_test(origin)
        assert hit is not None and hit.layer_id == mask_layer.layer_id, (
            None if hit is None else hit.layer_id,
            mask_layer.layer_id,
            vector_layer_id,
        )

        QTest.mousePress(
            viewer,
            Qt.MouseButton.LeftButton,
            Qt.NoModifier,
            origin.toPoint(),
        )
        assert viewer._editor_movement_interaction._active == "layer"
        assert viewer._editor_movement_interaction._snapping._session is not None
        latencies_ms: list[float] = []
        for jittered_endpoint in jittered_endpoints:
            assert jittered_endpoint is not None
            started = interaction_clock()
            QTest.mouseMove(viewer, jittered_endpoint.toPoint(), delay=0)
            harness.drain_events()
            latencies_ms.append((interaction_clock() - started) * 1000.0)
            box = viewer._editor_movement_interaction._layers.transform_box_state()
            assert box is not None
            assert box.transform.dx == pytest.approx(expected_dx)
            assert box.transform.dy == pytest.approx(expected_dy)
        assert max(stable_latency_samples(latencies_ms)) < 32.0, latencies_ms
        QTest.mouseRelease(
            viewer,
            Qt.MouseButton.LeftButton,
            Qt.NoModifier,
            endpoint.toPoint(),
        )
        harness.drain_events()

        transform = viewer.layerTransform(active_scene.scene_id, mask_layer.layer_id)
        assert transform is not None
        assert transform.dx() == pytest.approx(expected_dx)
        assert transform.dy() == pytest.approx(expected_dy)
        assert moving_bounds.left() + transform.dx() == pytest.approx(
            target_bounds.left()
        )
        assert moving_bounds.bottom() + transform.dy() == pytest.approx(
            target_bounds.bottom()
        )

        viewer.setControlMode(viewer.CONTROL_MODE_PANZOOM)
        for zoom in (0.75, 1.0, 1.75):
            anchor = viewer.view().scene_to_panel_point(
                QPointF(target_bounds.left(), 500.0)
            )
            assert anchor is not None
            viewer.applyZoom(zoom, anchor)
            harness.drain_events(wait_ms=5)
            assert harness.wait_for_render_refinement_idle()
            edge = viewer.view().scene_to_panel_point(
                QPointF(target_bounds.left(), 500.0)
            )
            assert edge is not None

            assert viewer.setMaskProperties(mask_id, opacity=0.0)
            harness.drain_events(wait_ms=5)
            assert harness.wait_for_render_refinement_idle()
            target_only_image = harness.capture()
            target_only = qimage_to_numpy_argb32(target_only_image)
            device_scale = target_only_image.devicePixelRatio()
            row_index = round(edge.y() * device_scale)
            expected_pixel_x = edge.x() * device_scale
            background_x = max(0, int(np.floor(expected_pixel_x)) - 10)
            background = target_only[row_index, background_x, :3].astype(np.int16)
            target_signal = np.max(
                np.abs(target_only[row_index, :, :3].astype(np.int16) - background),
                axis=1,
            )

            assert viewer.setMaskProperties(
                mask_id,
                color=QColor(40, 220, 90),
                opacity=1.0,
            )
            harness.drain_events(wait_ms=5)
            assert harness.wait_for_render_refinement_idle()
            combined = qimage_to_numpy_argb32(harness.capture())
            mask_signal = np.max(
                np.abs(
                    combined[row_index, :, :3].astype(np.int16)
                    - target_only[row_index, :, :3].astype(np.int16)
                ),
                axis=1,
            )
            target_edge_pixel = _first_edge_pixel(target_signal, expected_pixel_x)
            mask_edge_pixel = _first_edge_pixel(mask_signal, expected_pixel_x)
            assert abs(target_edge_pixel - expected_pixel_x) <= 1.0 + 1e-6
            assert abs(target_edge_pixel - mask_edge_pixel) <= 1
            target_strong_edge = _first_edge_pixel(
                target_signal,
                expected_pixel_x,
                threshold=64,
            )
            mask_strong_edge = _first_edge_pixel(
                mask_signal,
                expected_pixel_x,
                threshold=64,
            )
            assert abs(target_strong_edge - expected_pixel_x) <= 1.0 + 1e-6
            assert abs(mask_strong_edge - expected_pixel_x) <= 1.0 + 1e-6
            assert abs(target_strong_edge - mask_strong_edge) <= 1

        assert viewer.undoSceneEdit()
        harness.drain_events()
        reverted = viewer.layerTransform(active_scene.scene_id, mask_layer.layer_id)
        assert reverted is not None
        assert (reverted.dx(), reverted.dy()) == (0.0, 0.0)
        assert viewer.redoSceneEdit()
        harness.drain_events()
        restored = viewer.layerTransform(active_scene.scene_id, mask_layer.layer_id)
        assert restored is not None
        assert restored.dx() == pytest.approx(expected_dx)
        assert restored.dy() == pytest.approx(expected_dy)

        document = viewer.editor.compositions.get(composition_id)
        assert document is not None
        archive = tmp_path / "fractional-snapping.cutecanvas"
        viewer.editor.persistence.save(document, archive)
        document.remove()
        loaded = viewer.editor.persistence.load(archive)
        loaded_scene = viewer.currentScene()
        assert loaded.id == composition_id
        assert loaded_scene is not None
        persisted = viewer.layerTransform(loaded_scene.scene_id, mask_layer.layer_id)
        assert persisted is not None
        assert persisted.dx() == pytest.approx(expected_dx)
        assert persisted.dy() == pytest.approx(expected_dy)
    finally:
        harness.close()
