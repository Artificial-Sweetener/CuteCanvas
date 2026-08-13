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
"""Public raster-surface contract tests through a mounted mask feature."""

from __future__ import annotations

import time

from PySide6.QtCore import QRect, QRectF
from PySide6.QtGui import QColor, QImage

from cutecanvas import LayerPolicy, RasterExtentPolicy
from cutecanvas.painting import BrushStrokeSegment
from cutecanvas_test_support.mask_test_utils import drain_mask_jobs
from qpane.scene.raster import RasterBounds


def _attached_mask(qpane, manager, image_id):
    """Create and attach one mask, returning its public workflow metadata."""
    mask_id = manager.create_mask(QImage(8, 8, QImage.Format_Grayscale8))
    assert qpane.mask_service.layers.attach_to_composition(
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
    before = layer.coverage.raster.snapshot_array()

    state = qpane.rasterSurfaceState(info.scene_id, info.layer_id)
    assert state is not None
    assert state.bounds == QRect(0, 0, 8, 8)
    assert state.extent_policy is RasterExtentPolicy.EXPAND_ON_WRITE

    assert qpane.setRasterExtentPolicy(
        info.scene_id,
        info.layer_id,
        RasterExtentPolicy.FIXED,
    )
    updated = qpane.rasterSurfaceState(info.scene_id, info.layer_id)
    assert updated is not None
    assert updated.bounds == state.bounds
    assert updated.extent_policy is RasterExtentPolicy.FIXED
    assert updated.structure_revision == state.structure_revision + 1
    assert updated.content_revision == state.content_revision
    assert (layer.coverage.raster.snapshot_array() == before).all()


def test_mask_coverage_can_select_and_delete_through_generic_layer_editing(
    qpane_with_mask,
) -> None:
    """Masks should behave as selection sources and editable raster layers."""
    qpane, manager, image_id = qpane_with_mask
    mask_id, info = _attached_mask(qpane, manager, image_id)
    layer = manager.get_layer(mask_id)
    assert layer is not None
    layer.coverage.raster.fill(255)
    qpane.setLayerInteractionPolicy(
        info.scene_id,
        info.layer_id,
        LayerPolicy(
            selectable=True,
            movable=True,
            pixel_editable=True,
        ),
    )
    assert qpane.setSelectedLayer(info.scene_id, info.layer_id)
    assert qpane.selectLayerCoverage(info.scene_id, info.layer_id)
    assert qpane.deleteSelectedPixels()
    assert not layer.coverage.raster.snapshot_array().any()

    assert qpane.undoSceneEdit()
    assert (layer.coverage.raster.snapshot_array() == 255).all()
    assert qpane.redoSceneEdit()
    assert not layer.coverage.raster.snapshot_array().any()


def test_unbounded_mask_selection_projects_only_canvas_relevant_sparse_pixels(
    qpane_with_mask,
    qapp,
) -> None:
    """Saved-selection projection must not materialize distant off-canvas gaps."""
    qpane, manager, image_id = qpane_with_mask
    mask_id, info = _attached_mask(qpane, manager, image_id)
    layer = manager.get_layer(mask_id)
    assert layer is not None
    layer.coverage.raster.fill(0)
    assert qpane.setRasterExtentPolicy(
        info.scene_id,
        info.layer_id,
        RasterExtentPolicy.UNBOUNDED,
    )
    for bounds in (
        QRect(2, 2, 2, 2),
        QRect(1_000_000, 1_000_000, 8, 8),
    ):
        local = RasterBounds.from_qrect(bounds)
        assert layer.coverage.raster.ensure_writable(local).writable == local
        storage = layer.coverage.raster.storage_rect(local)
        assert storage is not None
        layer.coverage.raster.mutate_storage_region(
            storage,
            lambda pixels, _image: pixels.fill(255),
        )
    qpane.invalidateActiveMaskCache()
    allocated = layer.coverage.raster.allocated_bytes

    assert qpane.selectLayerCoverage(info.scene_id, info.layer_id)
    selection = qpane.pixelSelectionState()

    assert selection is not None
    assert selection.bounds == QRect(2, 2, 2, 2)
    assert selection.coverage is not None
    assert selection.coverage.size() == QRect(2, 2, 2, 2).size()
    assert layer.coverage.raster.allocated_bytes == allocated

    def visible_sampled_mask_items():
        """Return sampled products after the asynchronous hybrid source settles."""
        current_plan = qpane.view().calculateRenderPlan(is_blank=False)
        if current_plan is None:
            return []
        return [
            item
            for item in current_plan.render_items
            if item.descriptor.layer_id == info.layer_id
            and bool(getattr(item, "tiles", ()))
        ]

    _wait_for(qapp, lambda: len(visible_sampled_mask_items()) == 1)
    plan = qpane.view().calculateRenderPlan(is_blank=False)
    assert plan is not None
    visible_mask_items = [
        item
        for item in plan.render_items
        if item.descriptor.layer_id == info.layer_id
        and bool(getattr(item, "tiles", ()))
    ]
    assert len(visible_mask_items) == 1
    sampled_tiles = visible_mask_items[0].tiles
    assert sampled_tiles
    assert max(tile.image.width() for tile in sampled_tiles) <= 514
    assert max(tile.image.height() for tile in sampled_tiles) <= 514


def test_mask_delete_projects_through_scaled_transform_and_offset_bounds(
    qpane_with_mask,
    qapp,
) -> None:
    """Generic deletion must map scene coverage into offset local storage exactly."""
    qpane, manager, image_id = qpane_with_mask
    mask_id, info = _attached_mask(qpane, manager, image_id)
    layer = manager.get_layer(mask_id)
    assert layer is not None
    layer.coverage.raster.fill(255)
    completions: list[tuple] = []
    qpane.rasterBoundsRequestCompleted.connect(
        lambda *args: completions.append(tuple(args))
    )
    request_id = qpane.requestRasterBounds(
        info.scene_id,
        info.layer_id,
        QRect(-2, -1, 12, 10),
    )
    assert request_id is not None
    _wait_for(qapp, lambda: bool(completions))
    assert completions[-1][3] is True
    qpane.setLayerInteractionPolicy(
        info.scene_id,
        info.layer_id,
        LayerPolicy(
            selectable=True,
            movable=True,
            pixel_editable=True,
        ),
    )
    assert qpane.setLayerPlacement(
        info.scene_id,
        info.layer_id,
        QRectF(10.0, 20.0, 24.0, 20.0),
    )
    assert qpane.setSelectedLayer(info.scene_id, info.layer_id)
    selection = QImage(8, 8, QImage.Format_Grayscale8)
    selection.fill(255)
    assert qpane.setPixelSelection(selection, QRect(14, 24, 8, 8))
    storage_bounds = RasterBounds(-2, -1, 12, 10)
    before = layer.coverage.raster.capture_region(storage_bounds)

    assert qpane.deleteSelectedPixels()
    after = layer.coverage.raster.capture_region(storage_bounds)
    expected = before.copy()
    expected[2:6, 2:6] = 0
    assert (after == expected).all()
    assert qpane.undoSceneEdit()
    assert (layer.coverage.raster.capture_region(storage_bounds) == before).all()
    assert qpane.redoSceneEdit()
    assert (layer.coverage.raster.capture_region(storage_bounds) == expected).all()


def test_mask_brush_preview_and_commit_respect_pixel_selection(
    qpane_with_mask,
    qapp,
) -> None:
    """Selection-constrained strokes must never preview or persist outside coverage."""
    qpane, manager, image_id = qpane_with_mask
    mask_id, _info = _attached_mask(qpane, manager, image_id)
    layer = manager.get_layer(mask_id)
    service = qpane.mask_service
    assert layer is not None
    assert service is not None
    selection = QImage(4, 8, QImage.Format_Grayscale8)
    selection.fill(255)
    assert qpane.setPixelSelection(selection, QRect(0, 0, 4, 8))

    service.stroke_interactions.apply(
        BrushStrokeSegment.fixed((0.0, 4.0), (7.0, 4.0), 4.0, False)
    )
    preview = service.getColorizedMask(layer)
    assert preview is not None
    preview_image = preview.toImage()
    assert preview_image.pixelColor(2, 4).alpha() > 0
    assert preview_image.pixelColor(6, 4).alpha() == 0

    service.stroke_interactions.commit()
    drain_mask_jobs(qpane)
    pixels = layer.coverage.raster.snapshot_array()
    assert pixels[4, 2] == 255
    assert pixels[4, 6] == 0
    assert qpane.undoSceneEdit()
    assert not layer.coverage.raster.snapshot_array().any()


def test_transformed_mask_brush_preview_and_commit_share_scene_selection(
    qpane_with_mask,
) -> None:
    """Moved and scaled mask authoring must project the active scene selection."""
    qpane, manager, image_id = qpane_with_mask
    mask_id, info = _attached_mask(qpane, manager, image_id)
    layer = manager.get_layer(mask_id)
    service = qpane.mask_service
    assert layer is not None
    assert service is not None
    qpane.setLayerInteractionPolicy(
        info.scene_id,
        info.layer_id,
        LayerPolicy(selectable=True, movable=True),
    )
    assert qpane.setLayerPlacement(
        info.scene_id,
        info.layer_id,
        QRectF(-4.0, -4.0, 16.0, 16.0),
    )
    selection = QImage(4, 8, QImage.Format_Grayscale8)
    selection.fill(255)
    assert qpane.setPixelSelection(selection, QRect(2, 0, 4, 8))

    service.stroke_interactions.apply(
        BrushStrokeSegment.fixed((0.0, 4.0), (7.0, 4.0), 4.0, False)
    )
    preview = service.getColorizedMask(layer)
    assert preview is not None
    preview_image = preview.toImage()
    assert preview_image.pixelColor(3, 4).alpha() > 0
    assert preview_image.pixelColor(1, 4).alpha() == 0
    assert preview_image.pixelColor(7, 4).alpha() == 0

    service.stroke_interactions.commit()
    drain_mask_jobs(qpane)
    pixels = layer.coverage.raster.snapshot_array()
    assert pixels[4, 3] == 255
    assert pixels[4, 1] == 0
    assert pixels[4, 7] == 0
    assert qpane.undoSceneEdit()
    assert not layer.coverage.raster.snapshot_array().any()


def test_public_bounds_request_is_async_undoable_and_keeps_transform(
    qpane_with_mask,
    qapp,
):
    """Pad/crop should preserve local pixels, transform, and complete via signal."""
    qpane, manager, image_id = qpane_with_mask
    mask_id, info = _attached_mask(qpane, manager, image_id)
    layer = manager.get_layer(mask_id)
    assert layer is not None
    layer.coverage.raster.mutate(lambda pixels, _image: pixels.__setitem__((3, 4), 255))
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
    assert layer.coverage.authored_bounds == RasterBounds(-2, -1, 12, 11)
    assert layer.coverage.raster.snapshot_array()[4, 6] == 255
    moved_instance = qpane.mask_service.layer_instance_for_mask(mask_id)
    assert moved_instance is not None
    assert moved_instance.transform == transform
    assert qpane.undoMaskEdit()
    assert layer.coverage.raster.bounds.to_qrect() == QRect(0, 0, 8, 8)
    assert layer.coverage.authored_bounds == RasterBounds(0, 0, 8, 8)
    assert layer.coverage.raster.snapshot_array()[3, 4] == 255
    assert qpane.redoMaskEdit()
    assert layer.coverage.raster.bounds.to_qrect() == QRect(-2, -1, 12, 11)
    assert layer.coverage.authored_bounds == RasterBounds(-2, -1, 12, 11)


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
    """Detached layer work should terminate while retaining its project resource."""
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
    assert qpane.removeMaskFromComposition(image_id, mask_id)
    _wait_for(qapp, lambda: bool(completions))

    assert completions[0][:4] == (
        request_id,
        info.scene_id,
        info.layer_id,
        False,
    )
    assert manager.get_layer(mask_id) is not None
