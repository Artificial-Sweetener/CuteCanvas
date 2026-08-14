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
"""Public whole-layer coverage modification and visual-opacity tests."""

from __future__ import annotations

import time
from collections.abc import Callable

import numpy as np
import pytest
from PySide6.QtGui import QColor
from PySide6.QtTest import QSignalSpy

from cutecanvas import (
    LayerEdgeModificationResult,
    LayerEdgeOperation,
    RasterExtentPolicy,
)
from qpane.sdk.raster import numpy_to_qimage_grayscale8
from qpane.sdk.scene import RasterBounds


@pytest.mark.parametrize(
    "extent_policy",
    (RasterExtentPolicy.FIXED, RasterExtentPolicy.EXPAND_ON_WRITE),
)
def test_layer_edge_preview_and_commit_cannot_escape_canvas_aperture(
    qapp,
    qpane_with_mask,
    extent_policy: RasterExtentPolicy,
) -> None:
    """Canvas-scoped edge edits must stay bounded independently of storage policy."""

    canvas, manager, composition_id = qpane_with_mask
    before = np.zeros((8, 8), dtype=np.uint8)
    before[0, 0] = 255
    before[7, 7] = 255
    mask_id = manager.create_mask_from_image(numpy_to_qimage_grayscale8(before))
    assert canvas.mask_service.layers.attach_to_composition(
        mask_id,
        composition_id,
        color=QColor(220, 30, 80),
    )
    assert canvas.mask_service.controller.setActiveMaskID(mask_id)
    info = next(
        mask
        for mask in canvas.listMasksForComposition(composition_id)
        if mask.mask_id == mask_id
    )
    assert info.scene_id is not None and info.layer_id is not None
    state = canvas.rasterSurfaceState(info.scene_id, info.layer_id)
    assert state is not None
    if state.extent_policy is not extent_policy:
        assert canvas.setRasterExtentPolicy(
            info.scene_id,
            info.layer_id,
            extent_policy,
        )

    session_id = canvas.beginLayerEdgePreview(info.scene_id, info.layer_id)
    assert session_id is not None
    assert (
        canvas.updateLayerEdgePreview(session_id, LayerEdgeOperation.EXPAND, 2)
        is not None
    )
    try:
        preview_bounds = _wait_for_value(
            qapp,
            lambda: _transient_source_bounds(canvas),
        )
        assert RasterBounds(0, 0, 8, 8).contains(preview_bounds)
    finally:
        assert canvas.cancelLayerEdgePreview(session_id)
    assert np.array_equal(manager.get_layer(mask_id).coverage.snapshot().pixels, before)

    completed = QSignalSpy(canvas.layerEdgeModificationCompleted)
    request_id = canvas.expandLayerEdges(info.scene_id, info.layer_id, 2)
    assert request_id is not None
    _wait_for(qapp, lambda: completed.count() == 1)
    result = completed.at(0)[0]
    assert isinstance(result, LayerEdgeModificationResult)
    assert result.succeeded
    expanded = manager.get_layer(mask_id).coverage.snapshot()
    assert expanded.bounds is not None
    assert RasterBounds(0, 0, 8, 8).contains(expanded.bounds)

    assert canvas.undoMaskEdit()
    assert np.array_equal(manager.get_layer(mask_id).coverage.snapshot().pixels, before)
    assert canvas.redoMaskEdit()
    redone = manager.get_layer(mask_id).coverage.snapshot()
    assert redone.bounds is not None
    assert RasterBounds(0, 0, 8, 8).contains(redone.bounds)


def test_layer_edge_preview_rejects_product_that_escapes_canvas_aperture(
    qapp,
    qpane_with_mask,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shared preview owner must fail closed before presenting a bad product."""

    from cutecanvas.coverage import CoverageSnapshot
    from cutecanvas.runtime import coverage_modification_preview

    canvas, manager, composition_id = qpane_with_mask
    mask_id = manager.create_mask_from_image(
        numpy_to_qimage_grayscale8(np.full((4, 4), 255, dtype=np.uint8))
    )
    assert canvas.mask_service.layers.attach_to_composition(
        mask_id,
        composition_id,
        color=QColor(220, 30, 80),
    )
    info = next(
        mask
        for mask in canvas.listMasksForComposition(composition_id)
        if mask.mask_id == mask_id
    )
    assert info.scene_id is not None and info.layer_id is not None

    def escaped_product(*_args, **_kwargs) -> CoverageSnapshot:
        """Return a malformed backend product with newly authored exterior pixels."""

        return CoverageSnapshot(
            RasterBounds(-1, -1, 6, 6),
            RasterExtentPolicy.EXPAND_ON_WRITE,
            np.full((6, 6), 255, dtype=np.uint8),
        )

    monkeypatch.setattr(
        coverage_modification_preview,
        "build_coverage_edge_modification",
        escaped_product,
    )
    completed = QSignalSpy(canvas.layerEdgeModificationCompleted)
    session_id = canvas.beginLayerEdgePreview(info.scene_id, info.layer_id)
    assert session_id is not None
    assert canvas.updateLayerEdgePreview(session_id, LayerEdgeOperation.EXPAND, 1)
    assert completed.wait(3000)
    result = completed.at(0)[0]
    assert isinstance(result, LayerEdgeModificationResult)
    assert not result.succeeded
    assert result.message == "layer product escaped canvas aperture"
    assert canvas.view().calculateRenderPlan(is_blank=False).transient_raster is None
    assert manager.get_layer(mask_id).coverage.snapshot().bounds == RasterBounds(
        0, 0, 4, 4
    )


def test_generic_layer_edge_edit_bakes_once_and_restores_exactly_on_undo(
    qapp,
    qpane_with_mask,
) -> None:
    """A whole-mask expansion must use generic routing and one reversible edit."""
    canvas, manager, composition_id = qpane_with_mask
    before = np.zeros((8, 8), dtype=np.uint8)
    before[3:5, 3:5] = 180
    mask_id = manager.create_mask_from_image(numpy_to_qimage_grayscale8(before))
    assert canvas.mask_service.layers.attach_to_composition(
        mask_id,
        composition_id,
        color=QColor(220, 30, 80),
    )
    assert canvas.mask_service.controller.setActiveMaskID(mask_id)
    info = canvas.listMasksForComposition(composition_id)[0]
    assert info.scene_id is not None and info.layer_id is not None
    completed = QSignalSpy(canvas.layerEdgeModificationCompleted)

    request_id = canvas.expandLayerEdges(info.scene_id, info.layer_id, 2)
    assert request_id is not None
    _wait_for(qapp, lambda: completed.count() == 1)
    result = completed.at(0)[0]
    assert isinstance(result, LayerEdgeModificationResult)
    assert result.request_id == request_id
    assert result.operation is LayerEdgeOperation.EXPAND
    assert result.succeeded
    expanded = manager.get_layer(mask_id).coverage.snapshot().pixels
    assert np.count_nonzero(expanded) > np.count_nonzero(before)

    assert canvas.undoMaskEdit()
    restored = manager.get_layer(mask_id).coverage.snapshot().pixels
    assert np.array_equal(restored, before)


def test_preview_burst_uses_latest_value_and_commits_one_history_entry(
    qapp,
    qpane_with_mask,
) -> None:
    """Repeated preview updates must derive from one base and settle only once."""
    canvas, manager, composition_id = qpane_with_mask
    before = np.zeros((8, 8), dtype=np.uint8)
    before[3:5, 3:5] = 255
    mask_id = manager.create_mask_from_image(numpy_to_qimage_grayscale8(before))
    assert canvas.mask_service.layers.attach_to_composition(
        mask_id,
        composition_id,
        color=QColor(50, 170, 240),
    )
    assert canvas.mask_service.controller.setActiveMaskID(mask_id)
    info = canvas.listMasksForComposition(composition_id)[0]
    assert info.scene_id is not None and info.layer_id is not None
    session_id = canvas.beginLayerEdgePreview(info.scene_id, info.layer_id)
    assert session_id is not None
    assert (
        canvas.updateLayerEdgePreview(session_id, LayerEdgeOperation.EXPAND, 1)
        is not None
    )
    assert (
        canvas.updateLayerEdgePreview(session_id, LayerEdgeOperation.EXPAND, 3)
        is not None
    )
    completed = QSignalSpy(canvas.layerEdgeModificationCompleted)
    assert canvas.settleLayerEdgePreview(session_id)
    _wait_for(qapp, lambda: completed.count() == 1)
    expanded = manager.get_layer(mask_id).coverage.snapshot().pixels
    expected_nonzero = np.count_nonzero(expanded)
    assert expected_nonzero == 64

    assert canvas.undoMaskEdit()
    assert not canvas.undoMaskEdit()
    restored = manager.get_layer(mask_id).coverage.snapshot().pixels
    assert np.array_equal(restored, before)


def test_generic_visual_opacity_preserves_authored_coverage(
    qpane_with_mask,
) -> None:
    """Layer opacity must alter presentation state without quantizing coverage."""
    canvas, manager, composition_id = qpane_with_mask
    values = np.arange(64, dtype=np.uint8).reshape((8, 8)) * 4
    mask_id = manager.create_mask_from_image(numpy_to_qimage_grayscale8(values))
    assert canvas.mask_service.layers.attach_to_composition(
        mask_id,
        composition_id,
        color=QColor(240, 80, 30),
    )
    info = canvas.listMasksForComposition(composition_id)[0]
    assert info.scene_id is not None and info.layer_id is not None

    assert canvas.setLayerOpacity(info.scene_id, info.layer_id, 0.25)
    updated = canvas.listMasksForComposition(composition_id)[0]
    assert updated.opacity == 0.25
    preserved = manager.get_layer(mask_id).coverage.snapshot().pixels
    assert np.array_equal(preserved, values)


def _wait_for(qapp, predicate, timeout: float = 5.0) -> None:
    """Process Qt events until asynchronous layer work settles."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("timed out waiting for layer edge modification")


def _wait_for_value(qapp, provider: Callable[[], object | None], timeout: float = 5.0):
    """Return the first available asynchronous value within a bounded wait."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        value = provider()
        if value is not None:
            return value
        time.sleep(0.005)
    raise AssertionError("timed out waiting for layer edge preview")


def _transient_source_bounds(canvas) -> RasterBounds | None:
    """Return the current public render plan's transient source bounds."""

    plan = canvas.view().calculateRenderPlan(is_blank=False)
    contribution = None if plan is None else plan.transient_raster
    return None if contribution is None else contribution.source_bounds
