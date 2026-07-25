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

"""Mounted Fill Selection and Paint Bucket workflow tests."""

from __future__ import annotations

import uuid

import numpy as np
from cutecanvas import CuteCanvas, LayerPolicy
from cutecanvas.coverage import (
    CoverageCombineMode,
    CoverageGeometryFactory,
    RasterCoverageItem,
    VectorCoverageItem,
)
from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QImage

from tests.helpers.execution_backend import ControlledExecution


def _mounted_mask_canvas(
    qapp,
) -> tuple[CuteCanvas, ControlledExecution, uuid.UUID, uuid.UUID]:
    """Return one active image, mask, and deterministic execution runtime."""
    execution = ControlledExecution()
    canvas = CuteCanvas(features=("mask",), execution_runtime=execution.runtime)
    canvas.resize(128, 96)
    image = QImage(32, 24, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.white)
    image_id = canvas.createCompositionFromImage(image, title="Fill workflow")
    mask_id = canvas.createBlankMask(QSize(32, 24))
    assert mask_id is not None
    service = canvas.mask_service
    assert service is not None
    instance = service.layer_instance_for_mask(mask_id, image_id)
    assert instance is not None
    qapp.processEvents()
    scene = canvas.currentScene()
    assert scene is not None
    canvas.setLayerInteractionPolicy(
        scene.scene_id,
        instance.layer_id,
        LayerPolicy(
            selectable=True,
            movable=True,
            pixel_editable=True,
        ),
    )
    assert canvas.setPaintTarget(scene.scene_id, instance.layer_id)
    return canvas, execution, image_id, mask_id


def test_paint_bucket_commits_one_retained_mask_edit(qapp) -> None:
    """A blank-mask fill should remain retained, visible, and undoable."""
    canvas, executor, _image_id, mask_id = _mounted_mask_canvas(qapp)
    try:
        bucket = canvas.paintBucketCoordinator()
        assert bucket.request(QPointF(4.0, 5.0))
        assert bucket.busy
        executor.run_operation("editor.paint.bucket")
        qapp.processEvents()
        layer = canvas.mask_service.assets.get_layer(mask_id)
        assert layer is not None
        assert not bucket.busy
        assert len(layer.coverage.retained.items) == 1
        assert isinstance(layer.coverage.retained.items[0], RasterCoverageItem)
        assert np.all(layer.coverage.snapshot().pixels == 255)
        assert canvas.undoSceneEdit()
        assert not layer.coverage.retained.items
        assert not np.any(layer.coverage.snapshot().pixels)
    finally:
        canvas.deleteLater()
        qapp.processEvents()


def test_fill_selection_projects_scene_coverage_into_active_mask(qapp) -> None:
    """Fill Selection should preserve soft coverage and commit atomically."""
    canvas, _executor, _image_id, mask_id = _mounted_mask_canvas(qapp)
    try:
        selection = QImage(7, 5, QImage.Format_Grayscale8)
        selection.fill(129)
        assert canvas.setPixelSelection(selection, QRect(6, 8, 7, 5))
        assert canvas.fillSelection(CoverageCombineMode.ADD)
        layer = canvas.mask_service.assets.get_layer(mask_id)
        assert layer is not None
        assert layer.coverage.coverage_value(6, 8) == 129
        assert layer.coverage.coverage_value(12, 12) == 129
        assert layer.coverage.coverage_value(5, 8) == 0
        assert canvas.undoSceneEdit()
        assert layer.coverage.coverage_value(6, 8) == 0
    finally:
        canvas.deleteLater()
        qapp.processEvents()


def test_paint_bucket_rejects_result_after_target_revision_changes(qapp) -> None:
    """Late worker output must not overwrite newer mask authorship."""
    canvas, executor, _image_id, mask_id = _mounted_mask_canvas(qapp)
    try:
        bucket = canvas.paintBucketCoordinator()
        assert bucket.request(QPointF(3.0, 3.0))
        layer = canvas.mask_service.assets.get_layer(mask_id)
        assert layer is not None
        before_revision = layer.coverage.revision
        layer.coverage.raster.mutate(
            lambda pixels, _image: pixels.__setitem__((0, 0), 73)
        )
        assert layer.coverage.revision != before_revision
        executor.run_operation("editor.paint.bucket")
        qapp.processEvents()
        assert not bucket.busy
        assert not layer.coverage.retained.items
        assert layer.coverage.coverage_value(0, 0) == 73
    finally:
        canvas.deleteLater()
        qapp.processEvents()


def test_explicit_mask_rasterization_is_pixel_stable_and_undoable(qapp) -> None:
    """Flattening retained geometry should preserve output and restore authorship."""
    canvas, _executor, _image_id, mask_id = _mounted_mask_canvas(qapp)
    try:
        item = VectorCoverageItem(
            uuid.uuid4(),
            CoverageGeometryFactory().ellipse(QRectF(3.0, 4.0, 12.0, 10.0)),
            feather_radius=2.0,
        )
        assert canvas.paintingCoordinator().commit_coverage_item(item)
        layer = canvas.mask_service.assets.get_layer(mask_id)
        assert layer is not None
        before = layer.coverage.snapshot()
        assert layer.coverage.has_retained_items

        assert canvas.rasterizeMaskCoverage(mask_id)
        after = layer.coverage.snapshot()
        assert not layer.coverage.has_retained_items
        assert after.bounds == before.bounds
        assert np.array_equal(after.pixels, before.pixels)

        assert canvas.undoSceneEdit()
        assert layer.coverage.has_retained_items
        restored = layer.coverage.snapshot()
        assert restored.bounds == before.bounds
        assert np.array_equal(restored.pixels, before.pixels)
    finally:
        canvas.deleteLater()
        qapp.processEvents()
