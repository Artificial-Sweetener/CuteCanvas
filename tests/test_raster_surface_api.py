#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Public raster-surface contract tests through a mounted mask feature."""

from __future__ import annotations

import time

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage

from qpane import RasterExtentPolicy

pytest_plugins = ("tests.test_mask_workflows",)


def _attached_mask(qpane, manager, image_id):
    """Create and attach one mask, returning its public workflow metadata."""
    mask_id = manager.create_mask(QImage(8, 8, QImage.Format_Grayscale8))
    assert qpane.mask_service.layers.attach(
        mask_id,
        image_id,
        color=QColor(255, 0, 0),
    )
    assert qpane.mask_service.controller.setActiveMaskID(mask_id)
    info = qpane._masks_controller.maskInfo(mask_id)
    assert info is not None
    return mask_id, info


def _wait_for(qapp, predicate, timeout: float = 3.0) -> None:
    """Process Qt events until ``predicate`` succeeds or the timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("timed out waiting for asynchronous raster request")


def test_public_raster_state_and_policy_preserve_bounds_and_pixels(qpane_with_mask):
    """Policy updates should be generic, structural-only scene mutations."""
    qpane, manager, image_id = qpane_with_mask
    mask_id, info = _attached_mask(qpane, manager, image_id)
    layer = manager.get_layer(mask_id)
    assert layer is not None
    before = layer.surface.snapshot_array()

    state = qpane.rasterSurfaceState(info.scene_id, info.layer_id)
    assert state is not None
    assert state.bounds == QRect(0, 0, 8, 8)
    assert state.extent_policy is RasterExtentPolicy.FIXED

    assert qpane.setRasterExtentPolicy(
        info.scene_id,
        info.layer_id,
        RasterExtentPolicy.EXPAND_ON_WRITE,
    )
    updated = qpane.rasterSurfaceState(info.scene_id, info.layer_id)
    assert updated is not None
    assert updated.bounds == state.bounds
    assert updated.structure_revision == state.structure_revision + 1
    assert updated.content_revision == state.content_revision
    assert (layer.surface.snapshot_array() == before).all()


def test_public_bounds_request_is_async_undoable_and_keeps_transform(
    qpane_with_mask,
    qapp,
):
    """Pad/crop should preserve local pixels, transform, and complete via signal."""
    qpane, manager, image_id = qpane_with_mask
    mask_id, info = _attached_mask(qpane, manager, image_id)
    layer = manager.get_layer(mask_id)
    assert layer is not None
    layer.surface.mutate(lambda pixels, _image: pixels.__setitem__((3, 4), 255))
    instance = qpane.mask_service.layer_instance_for_mask(mask_id)
    assert instance is not None
    transform = instance.transform
    completions: list[tuple] = []
    qpane.rasterBoundsRequestCompleted.connect(
        lambda *args: completions.append(tuple(args))
    )

    request_id = qpane.requestRasterBounds(
        info.scene_id,
        info.layer_id,
        QRect(-2, -1, 12, 11),
    )
    assert request_id is not None
    pending = qpane.rasterSurfaceState(info.scene_id, info.layer_id)
    assert pending is not None
    assert pending.pending_request_id == request_id
    _wait_for(qapp, lambda: bool(completions))

    assert completions[-1] == (
        request_id,
        info.scene_id,
        info.layer_id,
        True,
        "",
    )
    updated = qpane.rasterSurfaceState(info.scene_id, info.layer_id)
    assert updated is not None
    assert updated.bounds == QRect(-2, -1, 12, 11)
    assert layer.surface.snapshot_array()[4, 6] == 255
    moved_instance = qpane.mask_service.layer_instance_for_mask(mask_id)
    assert moved_instance is not None
    assert moved_instance.transform == transform
    assert qpane.undoMaskEdit()
    assert layer.surface.bounds.to_qrect() == QRect(0, 0, 8, 8)
    assert layer.surface.snapshot_array()[3, 4] == 255
    assert qpane.redoMaskEdit()
    assert layer.surface.bounds.to_qrect() == QRect(-2, -1, 12, 11)


def test_new_bounds_request_replaces_prior_work_exactly_once(
    qpane_with_mask,
    qapp,
):
    """One layer should publish one cancellation and one latest success."""
    qpane, manager, image_id = qpane_with_mask
    _mask_id, info = _attached_mask(qpane, manager, image_id)
    completions: list[tuple] = []
    qpane.rasterBoundsRequestCompleted.connect(
        lambda *args: completions.append(tuple(args))
    )

    first = qpane.requestRasterBounds(
        info.scene_id,
        info.layer_id,
        QRect(-100, -100, 512, 512),
    )
    second = qpane.requestRasterBounds(
        info.scene_id,
        info.layer_id,
        QRect(-2, -3, 16, 17),
    )
    assert first is not None
    assert second is not None
    _wait_for(qapp, lambda: len(completions) == 2)

    by_request = {completion[0]: completion for completion in completions}
    assert by_request[first][3:] == (
        False,
        "replaced by a newer bounds request",
    )
    assert by_request[second][3:] == (True, "")
    assert len(by_request) == 2
    state = qpane.rasterSurfaceState(info.scene_id, info.layer_id)
    assert state is not None
    assert state.bounds == QRect(-2, -3, 16, 17)


def test_noop_bounds_request_completes_without_history_or_revision_change(
    qpane_with_mask,
    qapp,
):
    """Applying identical bounds should remain an asynchronous structural no-op."""
    qpane, manager, image_id = qpane_with_mask
    mask_id, info = _attached_mask(qpane, manager, image_id)
    before = qpane.rasterSurfaceState(info.scene_id, info.layer_id)
    history_before = qpane.getMaskUndoState(mask_id)
    completions: list[tuple] = []
    qpane.rasterBoundsRequestCompleted.connect(
        lambda *args: completions.append(tuple(args))
    )
    assert before is not None
    assert history_before is not None

    request_id = qpane.requestRasterBounds(
        info.scene_id,
        info.layer_id,
        before.bounds,
    )
    assert request_id is not None
    _wait_for(qapp, lambda: bool(completions))

    assert completions == [(request_id, info.scene_id, info.layer_id, True, "")]
    after = qpane.rasterSurfaceState(info.scene_id, info.layer_id)
    history_after = qpane.getMaskUndoState(mask_id)
    assert after == before
    assert history_after == history_before


def test_bounds_request_rejects_result_after_layer_removal(
    qpane_with_mask,
    qapp,
):
    """Detached layer work should terminate without restoring deleted source state."""
    qpane, manager, image_id = qpane_with_mask
    mask_id, info = _attached_mask(qpane, manager, image_id)
    completions: list[tuple] = []
    qpane.rasterBoundsRequestCompleted.connect(
        lambda *args: completions.append(tuple(args))
    )

    request_id = qpane.requestRasterBounds(
        info.scene_id,
        info.layer_id,
        QRect(-8, -8, 32, 32),
    )
    assert request_id is not None
    assert qpane.removeMaskFromImage(image_id, mask_id)
    _wait_for(qapp, lambda: bool(completions))

    assert completions[0][:4] == (
        request_id,
        info.scene_id,
        info.layer_id,
        False,
    )
    assert manager.get_layer(mask_id) is None
