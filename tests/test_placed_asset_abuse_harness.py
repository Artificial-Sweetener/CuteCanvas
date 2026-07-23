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
"""Mounted and generation-controlled abuse proof for placed assets."""

from __future__ import annotations

import statistics
import uuid
from pathlib import Path

from cutecanvas import CuteCanvas, LayerPolicy
from cutecanvas.placed.source_reference import PlacedAssetReference
from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QColor, QImage, QTransform
from PySide6.QtWidgets import QApplication
from qpane.raster.image_conversion import qimage_to_numpy_argb32

from tests.harness.mounted_qpane import MountedQPaneHarness
from tests.harness.timing import (
    absolute_latency_assertions_are_isolated,
    interaction_clock,
)
from tests.helpers.executor_stubs import StubExecutor

_MEDIAN_UPDATE_BUDGET_MS = 16.0
_ISOLATED_OUTLIER_BUDGET_MS = 100.0


def _image(color: QColor, size: QSize) -> QImage:
    """Return a detached premultiplied raster for abuse operations."""
    image = QImage(size, QImage.Format_ARGB32_Premultiplied)
    image.fill(color)
    return image


def test_mounted_placed_instances_stay_exact_responsive_and_cache_shared(
    qapp: QApplication,
) -> None:
    """Hostile affine updates must remain bounded and redraw without crumbs."""
    harness = MountedQPaneHarness(
        qapp,
        image_size=QSize(1600, 900),
        widget_size=QSize(960, 540),
        mask_count=1,
        cache_budget_mb=64,
    )
    viewer = harness.viewer
    try:
        scene = viewer.currentScene()
        assert scene is not None
        layer_id = viewer.placeEmbeddedAsset(
            _image(QColor(20, 170, 220, 220), QSize(1024, 1024)),
            placement=QRectF(240.0, 80.0, 700.0, 700.0),
            interaction=LayerPolicy(selectable=True, movable=True),
        )
        assert layer_id is not None
        duplicate_id = viewer.duplicatePlacedAsset(scene.scene_id, layer_id)
        assert duplicate_id is not None
        assert viewer.setLayerTransform(
            scene.scene_id,
            duplicate_id,
            QTransform(0.45, 0.08, -0.06, 0.44, 720.0, 120.0),
        )
        harness.drain_events(wait_ms=15)
        plan = viewer.view().calculateRenderPlan()
        placed_items = [
            item
            for item in plan.render_items
            if item.descriptor.source.kind == "placed-asset"
        ]
        assert len(placed_items) == 2
        assert placed_items[0].asset_key != placed_items[1].asset_key
        assert placed_items[0].pyramid_asset_key == placed_items[1].pyramid_asset_key

        latencies: list[float] = []
        for index in range(120):
            angle = (index % 17) - 8
            transform = QTransform()
            transform.translate(300.0 + (index * 31) % 360, 100.0 + (index * 19) % 180)
            transform.rotate(angle)
            transform.scale(0.55, 0.55)
            started = interaction_clock()
            assert viewer.setLayerTransform(scene.scene_id, layer_id, transform)
            harness.drain_events()
            latencies.append((interaction_clock() - started) * 1000.0)

        renderer = viewer.view().presenter.renderer
        incremental = renderer.get_base_buffer()
        assert incremental is not None
        incremental_pixels = qimage_to_numpy_argb32(incremental.copy())
        viewer.markDirty()
        viewer.update()
        harness.drain_events()
        repaired = renderer.get_base_buffer()
        assert repaired is not None
        assert qimage_to_numpy_argb32(repaired.copy()).shape == incremental_pixels.shape
        assert (qimage_to_numpy_argb32(repaired.copy()) == incremental_pixels).all()
        assert statistics.median(latencies) < _MEDIAN_UPDATE_BUDGET_MS
        if absolute_latency_assertions_are_isolated():
            assert max(latencies) < _ISOLATED_OUTLIER_BUDGET_MS
    finally:
        harness.close()


def test_link_reload_storm_rejects_stale_workers_delete_and_teardown(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    """Late cancelled generations must never publish or resurrect removed sources."""
    executor = StubExecutor(name="placed-abuse")
    viewer = CuteCanvas(features=(), task_executor=executor)
    base = _image(QColor("white"), QSize(64, 64))
    image_id = uuid.uuid4()
    viewer.setImagesByID(viewer.imageMapFromLists((base,), ids=(image_id,)), image_id)
    completions: list[tuple] = []
    viewer.placedAssetRequestCompleted.connect(
        lambda *values: completions.append(tuple(values))
    )
    source_paths: list[Path] = []
    for index in range(24):
        path = tmp_path / f"generation-{index}.png"
        assert _image(QColor(index * 7, 40, 200), QSize(48, 32)).save(str(path))
        source_paths.append(path)
    try:
        created_id = viewer.placeLinkedAsset(source_paths[0])
        assert created_id is not None
        executor.run_category("placed_decode")
        qapp.processEvents()
        created = next(item for item in completions if item[0] == created_id)
        assert created[3] is True
        layer_id = created[2]
        scene = viewer.currentScene()
        assert isinstance(layer_id, uuid.UUID) and scene is not None

        request_ids: list[uuid.UUID] = []
        stale_workers = []
        for path in source_paths[1:]:
            pending = [
                record
                for record in executor.pending_tasks()
                if record.handle.category == "placed_decode"
            ]
            stale_workers.extend(
                record.runnable for record in pending if record.runnable is not None
            )
            request_id = viewer.relinkPlacedAsset(scene.scene_id, layer_id, path)
            assert request_id is not None
            request_ids.append(request_id)
        for worker in stale_workers:
            worker.run()
        executor.run_category("placed_decode")
        qapp.processEvents()
        qapp.processEvents()

        for request_id in request_ids:
            assert sum(item[0] == request_id for item in completions) == 1
        final_state = viewer.placedAssetState(scene.scene_id, layer_id)
        assert final_state is not None
        assert final_state.source_path == source_paths[-1]
        assert final_state.status == "ready"

        refresh_id = viewer.refreshPlacedAsset(scene.scene_id, layer_id)
        assert refresh_id is not None
        refresh_record = next(
            record
            for record in executor.pending_tasks()
            if record.handle.category == "placed_decode"
        )
        assert viewer.undoSceneEdit()
        assert viewer.undoSceneEdit()
        refresh_record.runnable.run()
        qapp.processEvents()
        assert sum(item[0] == refresh_id for item in completions) == 1
        assert next(item for item in completions if item[0] == refresh_id)[3] is False
        assert all(layer.layer_id != layer_id for layer in viewer.currentScene().layers)

        pending_id = viewer.placeLinkedAsset(source_paths[0])
        assert pending_id is not None
        pending_record = next(
            record
            for record in executor.pending_tasks()
            if record.handle.category == "placed_decode"
        )
        before_shutdown = len(completions)
        viewer._placed_asset_workflow.shutdown()
        pending_record.runnable.run()
        qapp.processEvents()
        assert len(completions) == before_shutdown + 1
        assert sum(item[0] == pending_id for item in completions) == 1
    finally:
        viewer.clearImages()
        viewer.deleteLater()
        qapp.processEvents()


def test_navigation_shared_refresh_and_rasterization_races_stay_scoped(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    """Inactive scenes and deleted layers must reject late work without resurrection."""
    executor = StubExecutor(name="placed-navigation-abuse")
    viewer = CuteCanvas(features=(), task_executor=executor)
    first_id, second_id = uuid.uuid4(), uuid.uuid4()
    base = _image(QColor("black"), QSize(1200, 900))
    viewer.setImagesByID(
        viewer.imageMapFromLists((base, base), ids=(first_id, second_id)),
        first_id,
    )
    source_path = tmp_path / "shared.png"
    assert _image(QColor("red"), QSize(1024, 1024)).save(str(source_path))
    completions: list[tuple] = []
    viewer.placedAssetRequestCompleted.connect(
        lambda *values: completions.append(tuple(values))
    )
    try:
        first_scene = viewer.currentScene()
        assert first_scene is not None
        create_id = viewer.placeLinkedAsset(source_path)
        assert create_id is not None
        executor.run_category("placed_decode")
        qapp.processEvents()
        layer_id = next(item for item in completions if item[0] == create_id)[2]
        assert isinstance(layer_id, uuid.UUID)
        duplicate_id = viewer.duplicatePlacedAsset(first_scene.scene_id, layer_id)
        assert duplicate_id is not None

        assert _image(QColor("blue"), QSize(1024, 1024)).save(str(source_path))
        refresh_id = viewer.refreshPlacedAsset(first_scene.scene_id, layer_id)
        assert refresh_id is not None
        viewer.setCurrentImageID(second_id)
        second_scene = viewer.currentScene()
        assert (
            second_scene is not None and second_scene.scene_id != first_scene.scene_id
        )
        executor.run_category("placed_decode")
        qapp.processEvents()
        refreshed = next(item for item in completions if item[0] == refresh_id)
        assert refreshed[1:4] == (first_scene.scene_id, layer_id, True)
        assert viewer.currentScene().scene_id == second_scene.scene_id

        viewer.setCurrentImageID(first_id)
        first_state = viewer.placedAssetState(first_scene.scene_id, layer_id)
        duplicate_state = viewer.placedAssetState(first_scene.scene_id, duplicate_id)
        assert first_state is not None and duplicate_state is not None
        assert first_state.asset_id == duplicate_state.asset_id
        shared_pixels = viewer.layerSourceCapabilities().rasters.source_image(
            PlacedAssetReference(first_state.asset_id)
        )
        assert shared_pixels is not None
        assert shared_pixels.pixelColor(500, 500) == QColor("blue")

        started = interaction_clock()
        raster_id = viewer.rasterizePlacedAsset(first_scene.scene_id, duplicate_id)
        submission_ms = (interaction_clock() - started) * 1000.0
        assert raster_id is not None
        assert submission_ms < _MEDIAN_UPDATE_BUDGET_MS
        assert viewer.undoSceneEdit()
        raster_record = next(
            record
            for record in executor.pending_tasks()
            if record.handle.category == "layer_rasterization"
        )
        raster_record.runnable.run()
        qapp.processEvents()
        raster_completion = next(item for item in completions if item[0] == raster_id)
        assert raster_completion[3] is False
        assert all(
            item.layer_id != duplicate_id for item in viewer.currentScene().layers
        )
        assert viewer.placedAssetState(first_scene.scene_id, layer_id) is not None
    finally:
        viewer.clearImages()
        viewer.deleteLater()
        qapp.processEvents()
