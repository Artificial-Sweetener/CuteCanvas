#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Tests for selection-priority editor movement and atomic history."""

from __future__ import annotations

import uuid

import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage

from qpane.composition.edit_controller import CompositionEditController
from qpane.composition.edit_history import CompositionEditHistory
from qpane.coverage import CoverageSnapshot
from qpane.editor.movement import EditorMovementInteraction
from qpane.editor.pixel_movement import SelectedPixelMovementController
from qpane.editor.selection_projection import LayerSelectionProjectionCache
from qpane.raster.assets import EditableRasterAssetStore
from qpane.raster.image_conversion import qimage_to_numpy_argb32
from qpane.raster.pixel_edits import EditableRasterPixelMutationOwner
from qpane.scene.layer_selection import SceneLayerSelectionController
from qpane.scene.model import (
    LayerContentCapabilities,
    LayerDescriptor,
    LayerInteractionPolicy,
    LayerKind,
    LayerPlacement,
    SceneDescriptor,
    SceneKind,
)
from qpane.scene.mutations import SceneMutationCoordinator
from qpane.scene.pixel_owners import LayerPixelOwnerRegistry
from qpane.scene.raster import (
    LayerTransform,
    RasterBounds,
    RasterExtentPolicy,
)
from qpane.scene.sources import EditableRasterSource
from qpane.selection import PixelSelectionService


def _movement_fixture(
    *,
    placement: LayerPlacement | None = None,
    transform: LayerTransform | None = None,
):
    """Build one real RGBA domain behind the generic movement boundary."""
    scene_id = uuid.uuid4()
    bounds = RasterBounds(0, 0, 6, 2)
    placement = placement or LayerPlacement(0.0, 0.0, 6.0, 2.0)
    image = QImage(6, 2, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))
    image.setPixelColor(1, 0, QColor(255, 0, 0, 255))
    image.setPixelColor(2, 0, QColor(0, 255, 0, 255))
    assets = EditableRasterAssetStore()
    asset = assets.create(image, extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE)
    layer = LayerDescriptor(
        scene_id=scene_id,
        layer_id=uuid.uuid4(),
        kind=LayerKind.RASTER,
        source=EditableRasterSource(asset.raster_id, 0),
        placement=placement,
        interaction=LayerInteractionPolicy(selectable=True, pixel_editable=True),
        capabilities=LayerContentCapabilities(raster_editable=True),
        raster_bounds=bounds,
        transform=transform or LayerTransform.from_placement(bounds, placement),
    )
    scene = SceneDescriptor(
        scene_id,
        SceneKind.EXPLICIT,
        LayerPlacement(0.0, 0.0, 6.0, 2.0),
        (layer,),
    )
    history = CompositionEditHistory()
    edits = CompositionEditController(history)
    mutations = SceneMutationCoordinator(lambda: scene, edit_controller=edits)
    layer_selection = SceneLayerSelectionController()
    layer_selection.select(scene_id, layer.layer_id)
    selection = PixelSelectionService()
    selection.restore(
        scene_id,
        CoverageSnapshot(
            RasterBounds(1, 0, 2, 1),
            RasterExtentPolicy.EXPAND_ON_WRITE,
            np.full((1, 2), 255, dtype=np.uint8),
        ),
    )
    registry = LayerPixelOwnerRegistry()
    registry.register(EditableRasterPixelMutationOwner(assets, lambda _bounds: None))
    previews: list[object] = []
    movement = SelectedPixelMovementController(
        active_scene=lambda: scene,
        scene_mutations=mutations,
        layer_selection=layer_selection,
        pixel_selection=selection,
        pixel_owners=registry,
        edits=edits,
        selection_projections=LayerSelectionProjectionCache(),
        preview_changed=lambda: previews.append(object()),
    )
    return movement, edits, assets, asset, selection, scene, layer, previews


def _cross_layer_fixture():
    """Build two compatible editable RGBA layers in one scene."""
    scene_id = uuid.uuid4()
    bounds = RasterBounds(0, 0, 6, 2)
    source_image = QImage(6, 2, QImage.Format_ARGB32_Premultiplied)
    source_image.fill(QColor(0, 0, 0, 0))
    source_image.setPixelColor(1, 0, QColor(255, 0, 0, 255))
    source_image.setPixelColor(2, 0, QColor(0, 255, 0, 255))
    target_image = QImage(6, 2, QImage.Format_ARGB32_Premultiplied)
    target_image.fill(QColor(0, 0, 0, 0))
    target_image.setPixelColor(5, 1, QColor(0, 0, 255, 255))
    assets = EditableRasterAssetStore()
    source_asset = assets.create(
        source_image,
        extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
    )
    target_asset = assets.create(
        target_image,
        extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
    )
    policy = LayerInteractionPolicy(selectable=True, pixel_editable=True)
    capabilities = LayerContentCapabilities(raster_editable=True)
    source_layer = LayerDescriptor(
        scene_id=scene_id,
        layer_id=uuid.uuid4(),
        kind=LayerKind.RASTER,
        source=EditableRasterSource(source_asset.raster_id, 0),
        placement=LayerPlacement(0.0, 0.0, 6.0, 2.0),
        interaction=policy,
        capabilities=capabilities,
        raster_bounds=bounds,
        transform=LayerTransform(),
    )
    target_layer = LayerDescriptor(
        scene_id=scene_id,
        layer_id=uuid.uuid4(),
        kind=LayerKind.RASTER,
        source=EditableRasterSource(target_asset.raster_id, 0),
        placement=LayerPlacement(0.0, 0.0, 6.0, 2.0),
        interaction=policy,
        capabilities=capabilities,
        raster_bounds=bounds,
        transform=LayerTransform(),
    )
    scene = SceneDescriptor(
        scene_id,
        SceneKind.EXPLICIT,
        LayerPlacement(0.0, 0.0, 6.0, 2.0),
        (source_layer, target_layer),
    )
    history = CompositionEditHistory()
    edits = CompositionEditController(history)
    mutations = SceneMutationCoordinator(lambda: scene, edit_controller=edits)
    layer_selection = SceneLayerSelectionController()
    layer_selection.select(scene_id, source_layer.layer_id)
    selection = PixelSelectionService()
    selection.restore(
        scene_id,
        CoverageSnapshot(
            RasterBounds(1, 0, 2, 1),
            RasterExtentPolicy.EXPAND_ON_WRITE,
            np.full((1, 2), 255, dtype=np.uint8),
        ),
    )
    registry = LayerPixelOwnerRegistry()
    registry.register(EditableRasterPixelMutationOwner(assets, lambda _bounds: None))
    movement = SelectedPixelMovementController(
        active_scene=lambda: scene,
        scene_mutations=mutations,
        layer_selection=layer_selection,
        pixel_selection=selection,
        pixel_owners=registry,
        edits=edits,
        selection_projections=LayerSelectionProjectionCache(),
        preview_changed=lambda: None,
    )
    return (
        movement,
        edits,
        selection,
        layer_selection,
        scene,
        source_layer,
        target_layer,
        source_asset,
        target_asset,
    )


def test_selected_pixels_remain_floating_after_release_then_anchor_atomically() -> None:
    """Pointer release must retain a non-destructive edit until explicit anchoring."""
    movement, edits, _assets, asset, selection, scene, _layer, previews = (
        _movement_fixture()
    )
    before = asset.surface.snapshot_qimage()

    assert movement.begin(QPointF(1.5, 0.5))
    assert movement.update(QPointF(3.5, 0.5))
    assert asset.surface.snapshot_qimage() == before
    assert movement.raster_preview is not None
    assert movement.raster_preview.delta_x == 2
    assert movement.preview_state is not None
    assert movement.preview_state.coverage is not None
    assert movement.preview_state.coverage.bounds == RasterBounds(3, 0, 2, 1)

    assert movement.finish(QPointF(3.5, 0.5))
    assert movement.active
    assert asset.surface.snapshot_qimage() == before
    assert not edits.can_undo(scene.scene_id)

    assert movement.anchor_to_source()
    after = qimage_to_numpy_argb32(asset.surface.snapshot_qimage())
    assert after[0, 1, 3] == 0
    assert after[0, 2, 3] == 0
    assert after[0, 3, 2] == 255
    assert after[0, 4, 1] == 255
    assert selection.state(scene.scene_id).coverage is not None
    assert selection.state(scene.scene_id).coverage.bounds == RasterBounds(3, 0, 2, 1)
    assert edits.can_undo(scene.scene_id)
    assert len(previews) >= 3

    assert edits.undo(scene.scene_id).changed
    assert asset.surface.snapshot_qimage() == before
    assert selection.state(scene.scene_id).coverage is not None
    assert selection.state(scene.scene_id).coverage.bounds == RasterBounds(1, 0, 2, 1)
    assert edits.redo(scene.scene_id).changed
    assert np.array_equal(
        qimage_to_numpy_argb32(asset.surface.snapshot_qimage()), after
    )


def test_floating_pixels_support_repeated_drags_and_lossless_cancel() -> None:
    """A released payload should remain movable while cancel preserves its source."""
    movement, edits, _assets, asset, selection, scene, _layer, _previews = (
        _movement_fixture()
    )
    before = asset.surface.snapshot_qimage()
    before_selection = selection.state(scene.scene_id).coverage

    assert movement.begin(QPointF(1.5, 0.5))
    assert movement.finish(QPointF(3.5, 0.5))
    assert movement.begin(QPointF(3.5, 0.5))
    assert movement.finish(QPointF(4.5, 0.5))
    assert movement.raster_preview is not None
    assert movement.raster_preview.delta_x == 3
    assert asset.surface.snapshot_qimage() == before

    assert movement.cancel()
    assert asset.surface.snapshot_qimage() == before
    assert selection.state(scene.scene_id).coverage == before_selection
    assert not edits.can_undo(scene.scene_id)


def test_suspending_active_drag_preserves_exact_floating_displacement() -> None:
    """Temporary input loss must retain the session and its last preview transition."""
    movement, _edits, _assets, asset, _selection, _scene, _layer, _previews = (
        _movement_fixture()
    )
    before = asset.surface.snapshot_qimage()

    assert movement.begin(QPointF(1.5, 0.5))
    assert movement.update(QPointF(3.5, 0.5))
    preview_before = movement.raster_preview
    assert preview_before is not None
    assert movement.suspend_drag()

    assert movement.active
    assert not movement.dragging
    assert movement.offset.x() == 2
    assert movement.raster_preview == preview_before
    assert asset.surface.snapshot_qimage() == before


def test_anchor_applies_the_exact_transition_exposed_to_rendering() -> None:
    """Durable source pixels must equal the immutable transition shown in preview."""
    movement, _edits, _assets, asset, _selection, _scene, _layer, _previews = (
        _movement_fixture()
    )

    assert movement.begin(QPointF(1.5, 0.5))
    assert movement.update(QPointF(3.5, 0.5))
    preview = movement.raster_preview
    assert preview is not None
    expected = np.array(preview.transition.after_pixels, copy=True)
    expected_bounds = preview.transition.patch_bounds

    assert movement.finish(QPointF(3.5, 0.5))
    assert movement.anchor_to_source()
    np.testing.assert_array_equal(
        asset.surface.capture_region(expected_bounds),
        expected,
    )


def test_floating_pixels_commit_across_layers_as_one_atomic_history_edit() -> None:
    """Cross-layer resolution should cut source, place target, and replay together."""
    (
        movement,
        edits,
        selection,
        layer_selection,
        scene,
        source_layer,
        target_layer,
        source_asset,
        target_asset,
    ) = _cross_layer_fixture()
    source_before = source_asset.surface.snapshot_qimage()
    target_before = target_asset.surface.snapshot_qimage()

    assert movement.begin(QPointF(1.5, 0.5))
    assert movement.finish(QPointF(3.5, 0.5))
    assert movement.anchor_to(scene.scene_id, target_layer.layer_id)

    source_after = qimage_to_numpy_argb32(source_asset.surface.snapshot_qimage())
    target_after_image = target_asset.surface.snapshot_qimage()
    target_after = qimage_to_numpy_argb32(target_after_image)
    assert not source_after[0, 1:3, 3].any()
    assert target_after[0, 3, 2] == 255
    assert target_after[0, 4, 1] == 255
    assert target_after[1, 5, 0] == 255
    assert layer_selection.current.layer_id == target_layer.layer_id
    assert selection.state(scene.scene_id).coverage.bounds == RasterBounds(3, 0, 2, 1)

    assert edits.undo(scene.scene_id).changed
    assert source_asset.surface.snapshot_qimage() == source_before
    assert target_asset.surface.snapshot_qimage() == target_before
    assert layer_selection.current.layer_id == source_layer.layer_id
    assert selection.state(scene.scene_id).coverage.bounds == RasterBounds(1, 0, 2, 1)

    assert edits.redo(scene.scene_id).changed
    assert target_asset.surface.snapshot_qimage() == target_after_image
    assert layer_selection.current.layer_id == target_layer.layer_id


def test_copy_float_preserves_source_pixels_when_anchored() -> None:
    """Copy mode should place a duplicate while leaving its origin unchanged."""
    movement, edits, _assets, asset, selection, scene, _layer, _previews = (
        _movement_fixture()
    )
    before = asset.surface.snapshot_qimage()

    assert movement.begin(QPointF(1.5, 0.5), copy=True)
    assert movement.finish(QPointF(3.5, 0.5))
    assert movement.raster_preview is not None
    assert not movement.cut_source
    assert movement.anchor_to_source()

    pixels = qimage_to_numpy_argb32(asset.surface.snapshot_qimage())
    assert pixels[0, 1, 2] == 255
    assert pixels[0, 2, 1] == 255
    assert pixels[0, 3, 2] == 255
    assert pixels[0, 4, 1] == 255
    assert selection.state(scene.scene_id).coverage.bounds == RasterBounds(3, 0, 2, 1)
    assert edits.undo(scene.scene_id).changed
    assert asset.surface.snapshot_qimage() == before
    assert selection.state(scene.scene_id).coverage.bounds == RasterBounds(1, 0, 2, 1)
    assert edits.redo(scene.scene_id).changed
    assert selection.state(scene.scene_id).coverage.bounds == RasterBounds(3, 0, 2, 1)


class _PixelsRejectingStart:
    """Selection branch double that rejects a move start."""

    def has_selection(self) -> bool:
        """Report an active selection."""
        return True

    def can_begin(self, _point: QPointF) -> bool:
        """Reject the tested point."""
        return False

    def begin(self, _point: QPointF, _copy: bool = False) -> bool:
        """Reject the tested point."""
        return False

    def cancel(self) -> bool:
        """Report no active sequence."""
        return False


class _PixelsWithoutSelection(_PixelsRejectingStart):
    """Pixel branch double reporting no active selection."""

    def has_selection(self) -> bool:
        """Report no active selection."""
        return False


class _LayerMovementSpy:
    """Layer branch double recording accidental fallthrough."""

    hovered = None

    def __init__(self) -> None:
        """Initialize without calls."""
        self.begin_calls = 0

    def clear_hover(self) -> bool:
        """Report no hover."""
        return False

    def begin(self, _point: QPointF) -> bool:
        """Record an invalid layer fallback."""
        self.begin_calls += 1
        return True

    def cancel(self) -> bool:
        """Report no active sequence."""
        return False


def test_active_selection_rejection_never_falls_through_to_layer_movement() -> None:
    """A click outside selected pixels must not move an underlying layer."""
    pixels = _PixelsRejectingStart()
    layers = _LayerMovementSpy()
    interaction = EditorMovementInteraction(
        pixels=pixels,
        layers=layers,
        panel_to_scene=lambda point: point,
        refresh_preview=lambda: None,
    )

    assert not interaction.begin(QPointF(50.0, 50.0))
    assert layers.begin_calls == 0


def test_no_selection_preserves_whole_layer_movement_branch() -> None:
    """The refactor must retain existing layer placement when ants are absent."""
    layers = _LayerMovementSpy()
    interaction = EditorMovementInteraction(
        pixels=_PixelsWithoutSelection(),
        layers=layers,
        panel_to_scene=lambda point: point,
        refresh_preview=lambda: None,
    )

    assert interaction.begin(QPointF(5.0, 5.0))
    assert layers.begin_calls == 1


def test_keyboard_nudge_moves_selected_pixels_without_pointer_hit_testing() -> None:
    """Arrow movement should retain the same atomic pixel-and-selection semantics."""
    movement, edits, _assets, asset, selection, scene, _layer, _previews = (
        _movement_fixture()
    )

    assert movement.nudge(1, 0)
    assert asset.surface.snapshot_qimage().pixelColor(1, 0).alpha() == 255
    assert movement.anchor_to_source()
    pixels = qimage_to_numpy_argb32(asset.surface.snapshot_qimage())
    assert pixels[0, 1, 3] == 0
    assert pixels[0, 3, 1] == 255
    state = selection.state(scene.scene_id)
    assert state.coverage is not None
    assert state.coverage.bounds == RasterBounds(2, 0, 2, 1)
    assert edits.undo(scene.scene_id).changed
    assert selection.state(scene.scene_id).coverage.bounds == RasterBounds(1, 0, 2, 1)


def test_move_selection_excludes_transparent_pixels_from_resulting_coverage() -> None:
    """Moved ants and pixels must share content-filtered coverage with transparent holes."""
    movement, edits, _assets, asset, selection, scene, _layer, _previews = (
        _movement_fixture()
    )
    geometric = CoverageSnapshot(
        RasterBounds(0, 0, 4, 1),
        RasterExtentPolicy.EXPAND_ON_WRITE,
        np.full((1, 4), 255, dtype=np.uint8),
    )
    assert selection.restore(scene.scene_id, geometric)

    assert movement.begin(QPointF(1.5, 0.5))
    assert movement.update(QPointF(2.5, 0.5))
    preview = movement.preview_state
    assert preview is not None
    assert preview.coverage is not None
    assert preview.coverage.bounds == RasterBounds(2, 0, 2, 1)
    np.testing.assert_array_equal(
        preview.coverage.pixels,
        np.array([[255, 255]], dtype=np.uint8),
    )

    assert movement.finish(QPointF(2.5, 0.5))
    assert movement.anchor_to_source()
    committed = selection.state(scene.scene_id).coverage
    assert committed is not None
    assert committed.bounds == RasterBounds(2, 0, 2, 1)
    np.testing.assert_array_equal(
        committed.pixels,
        np.array([[255, 255]], dtype=np.uint8),
    )
    pixels = qimage_to_numpy_argb32(asset.surface.snapshot_qimage())
    assert pixels[0, 1, 3] == 0
    assert pixels[0, 2, 2] == 255
    assert pixels[0, 3, 1] == 255

    assert edits.undo(scene.scene_id).changed
    restored = selection.state(scene.scene_id).coverage
    assert restored is not None
    assert restored.bounds == geometric.bounds
    np.testing.assert_array_equal(restored.pixels, geometric.pixels)
    assert edits.redo(scene.scene_id).changed
    redone = selection.state(scene.scene_id).coverage
    assert redone is not None
    assert redone.bounds == RasterBounds(2, 0, 2, 1)


def test_move_preserves_soft_selection_without_squaring_source_alpha() -> None:
    """Content occupancy should reject alpha zero without attenuating nonzero alpha twice."""
    movement, _edits, _assets, asset, selection, scene, _layer, _previews = (
        _movement_fixture()
    )
    image = asset.surface.snapshot_qimage()
    image.setPixelColor(1, 0, QColor(255, 0, 0, 128))
    asset.surface.restore_patch(
        asset.surface.bounds,
        qimage_to_numpy_argb32(image),
    )
    assert selection.restore(
        scene.scene_id,
        CoverageSnapshot(
            RasterBounds(1, 0, 1, 1),
            RasterExtentPolicy.EXPAND_ON_WRITE,
            np.array([[128]], dtype=np.uint8),
        ),
    )

    assert movement.nudge(2, 0)
    assert movement.anchor_to_source()

    committed = selection.state(scene.scene_id).coverage
    assert committed is not None
    np.testing.assert_array_equal(committed.pixels, np.array([[128]], np.uint8))
    moved_alpha = asset.surface.snapshot_qimage().pixelColor(3, 0).alpha()
    assert 62 <= moved_alpha <= 65


def test_selection_over_only_transparent_pixels_cannot_begin_content_move() -> None:
    """A geometric selection without selected layer content must remain nonmovable."""
    movement, _edits, _assets, asset, selection, scene, _layer, _previews = (
        _movement_fixture()
    )
    transparent = np.zeros((2, 6, 4), dtype=np.uint8)
    assert asset.surface.restore_patch(asset.surface.bounds, transparent)
    assert selection.restore(
        scene.scene_id,
        CoverageSnapshot(
            RasterBounds(0, 0, 6, 2),
            RasterExtentPolicy.EXPAND_ON_WRITE,
            np.full((2, 6), 255, dtype=np.uint8),
        ),
    )

    assert not movement.can_begin(QPointF(1.0, 1.0))
    assert not movement.begin(QPointF(1.0, 1.0))


def test_content_filtered_move_maps_transformed_layer_coverage_exactly() -> None:
    """Effective pixels and ants must share source-to-scene scaling and translation."""
    movement, _edits, _assets, _asset, selection, scene, _layer, _previews = (
        _movement_fixture(
            placement=LayerPlacement(10.0, 20.0, 12.0, 4.0),
            transform=LayerTransform(2.0, 2.0, 10.0, 20.0),
        )
    )
    assert selection.restore(
        scene.scene_id,
        CoverageSnapshot(
            RasterBounds(10, 20, 8, 2),
            RasterExtentPolicy.EXPAND_ON_WRITE,
            np.full((2, 8), 255, dtype=np.uint8),
        ),
    )

    assert movement.begin(QPointF(13.0, 21.0))
    assert movement.update(QPointF(17.0, 21.0))
    preview = movement.preview_state
    assert preview is not None
    assert preview.coverage is not None
    assert preview.coverage.bounds == RasterBounds(16, 20, 4, 2)
    raster_preview = movement.raster_preview
    assert raster_preview is not None
    assert raster_preview.delta_x == 2

    assert movement.finish(QPointF(17.0, 21.0))
    assert movement.anchor_to_source()
    committed = selection.state(scene.scene_id).coverage
    assert committed is not None
    assert committed.bounds == RasterBounds(16, 20, 4, 2)


def test_expand_on_write_content_move_retains_off_surface_pixels_and_history() -> None:
    """Filtered content moved off-canvas must survive and undo with exact bounds."""
    movement, edits, _assets, asset, selection, scene, _layer, _previews = (
        _movement_fixture()
    )
    before_bounds = asset.surface.bounds

    assert movement.nudge(-3, 0)
    assert movement.anchor_to_source()

    assert asset.surface.bounds == RasterBounds(-2, 0, 8, 2)
    moved = selection.state(scene.scene_id).coverage
    assert moved is not None
    assert moved.bounds == RasterBounds(-2, 0, 2, 1)
    assert edits.undo(scene.scene_id).changed
    assert asset.surface.bounds == before_bounds
    assert edits.redo(scene.scene_id).changed
    assert asset.surface.bounds == RasterBounds(-2, 0, 8, 2)
