#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Deterministic shared-brush and editable-color target contracts."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
from PySide6.QtCore import QPointF, QRect, QRectF
from PySide6.QtGui import QColor, QImage

from qpane import (
    BrushDynamics as PublicBrushDynamics,
)
from qpane import (
    BrushPreset as PublicBrushPreset,
)
from qpane import (
    PaintTargetKind,
    QPaneLayerInteractionPolicy,
    RasterExtentPolicy,
)
from qpane.painting import (
    BrushDabEngine,
    BrushOperation,
    BrushPreset,
    BrushSourceCoordinateSession,
    BrushStrokeSegment,
    BrushStrokeSession,
    BrushTipCache,
)
from qpane.painting.rendering import render_color_stroke, render_coverage_stroke

pytest_plugins = ("tests.test_mask_workflows",)


def _transparent_image(width: int, height: int) -> QImage:
    """Return one transparent premultiplied paint surface."""
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))
    return image


def test_source_coordinate_session_preserves_continuity_after_left_expansion() -> None:
    """A mutable zero-origin raster must not create a phantom cross-origin line."""
    coordinates = BrushSourceCoordinateSession((0.0, 0.0))
    initial = coordinates.layer_segment(
        BrushStrokeSegment.fixed((-82.0, 30.0), (-82.0, 30.0), 20.0, False),
        (0.0, 0.0),
    )
    continued = coordinates.layer_segment(
        BrushStrokeSegment.fixed((-82.0, 30.0), (3989.0, 30.0), 20.0, False),
        (-4096.0, 0.0),
    )

    assert initial.start == initial.end == (-82.0, 30.0)
    assert continued.start == (-82.0, 30.0)
    assert continued.end == (-107.0, 30.0)


def test_dab_engine_is_deterministic_for_dynamic_segments() -> None:
    """A dynamic segment must resolve identically without mutable random state."""
    segment = BrushStrokeSegment(
        start=(10.0, 20.0),
        end=(210.0, 85.0),
        start_diameter=8.0,
        end_diameter=31.0,
        hardness=0.45,
        opacity=0.7,
        flow=0.35,
        spacing=0.12,
        position_jitter=0.4,
        size_jitter=0.3,
        angle_jitter=0.5,
        seed=9182,
        sequence=14,
    )
    engine = BrushDabEngine()

    first = engine.segment_dabs(segment)
    second = engine.segment_dabs(segment)

    assert first == second
    assert len(first) > 40
    assert all(dab.opacity == 0.7 * 0.35 for dab in first)
    assert any(dab.center != first[0].center for dab in first[1:])


def test_textured_tips_are_deterministic_bounded_and_shared_across_formats() -> None:
    """Procedural grain must be reproducible and obey its strict cache ceiling."""
    cache = BrushTipCache(budget_bytes=9_000)
    segment = BrushStrokeSegment(
        start=(20.0, 20.0),
        end=(42.0, 20.0),
        start_diameter=18.0,
        end_diameter=18.0,
        texture_strength=0.65,
        texture_scale=4.0,
        texture_seed=71,
    )
    dabs = BrushDabEngine().segment_dabs(segment)
    first = cache.tip(
        diameter=dabs[0].diameter,
        hardness=dabs[0].hardness,
        texture_strength=dabs[0].texture_strength,
        texture_scale=dabs[0].texture_scale,
        texture_seed=dabs[0].texture_seed,
        angle=dabs[0].angle,
    )
    second = cache.tip(
        diameter=dabs[0].diameter,
        hardness=dabs[0].hardness,
        texture_strength=dabs[0].texture_strength,
        texture_scale=dabs[0].texture_scale,
        texture_seed=dabs[0].texture_seed,
        angle=dabs[0].angle,
    )
    assert second is first
    for diameter in range(8, 80, 3):
        cache.tip(
            diameter=float(diameter),
            hardness=0.5,
            texture_strength=0.7,
            texture_scale=3.0,
            texture_seed=diameter,
            angle=float(diameter),
        )
    assert cache.usage_bytes <= 9_000

    textured = replace(
        segment,
        hardness=0.4,
        opacity=0.8,
    )
    coverage, _preview = render_coverage_stroke(
        before=np.zeros((64, 64), dtype=np.uint8),
        dirty_rect=QRect(0, 0, 64, 64),
        segments=(textured,),
    )
    color = render_color_stroke(
        before=np.zeros((64, 64, 4), dtype=np.uint8),
        patch_bounds=QRect(0, 0, 64, 64),
        segments=(textured,),
        color=QColor(255, 255, 255),
    )
    assert np.array_equal(coverage, color[:, :, 3])
    assert 0 < np.count_nonzero(coverage) < coverage.size


def test_pointer_session_smooths_path_and_preserves_rich_tablet_samples() -> None:
    """One source-neutral session must stabilize and retain tablet dynamics."""
    session = BrushStrokeSession()
    session.begin(
        3,
        QPointF(0.0, 0.0),
        20.0,
        False,
        pressure=0.25,
        tilt_x=10.0,
        tilt_y=-5.0,
        rotation=12.0,
        tangential_pressure=-0.2,
    )
    segment = session.update(
        3,
        QPointF(100.0, 0.0),
        30.0,
        False,
        pressure=0.75,
        tilt_x=30.0,
        tilt_y=15.0,
        rotation=90.0,
        tangential_pressure=0.6,
        smoothing=0.5,
    )
    assert segment is not None
    assert 0.0 < segment.end[0] < 100.0
    assert segment.start_tilt_x == 10.0
    assert segment.end_tilt_y == 15.0
    assert segment.end_rotation == 90.0
    assert segment.end_tangential_pressure == 0.6


def test_color_renderer_supports_soft_paint_and_exact_erase() -> None:
    """Color and erase operations must preserve premultiplication and soft edges."""
    bounds = QRect(0, 0, 64, 64)
    transparent = np.zeros((64, 64, 4), dtype=np.uint8)
    paint = BrushStrokeSegment(
        start=(32.0, 32.0),
        end=(32.0, 32.0),
        start_diameter=32.0,
        end_diameter=32.0,
        hardness=0.25,
        opacity=0.8,
    )

    painted = render_color_stroke(
        before=transparent,
        patch_bounds=bounds,
        segments=(paint,),
        color=QColor(220, 80, 40, 255),
    )

    center_alpha = int(painted[32, 32, 3])
    edge_alpha = int(painted[32, 46, 3])
    assert 195 <= center_alpha <= 205
    assert 0 < edge_alpha < center_alpha
    assert np.all(painted[:, :, :3] <= painted[:, :, 3:4])

    erase = replace(paint, operation=BrushOperation.ERASE, hardness=1.0, opacity=1.0)
    erased = render_color_stroke(
        before=painted,
        patch_bounds=bounds,
        segments=(erase,),
        color=QColor(1, 2, 3),
    )
    assert int(erased[32, 32, 3]) == 0
    assert np.all(erased[32, 32] == 0)


def test_coverage_renderer_supports_soft_paint_and_soft_erase() -> None:
    """Coverage targets must use the same opacity and hardness semantics as color."""
    before = np.zeros((64, 64), dtype=np.uint8)
    paint = BrushStrokeSegment(
        start=(32.0, 32.0),
        end=(32.0, 32.0),
        start_diameter=32.0,
        end_diameter=32.0,
        hardness=0.25,
        opacity=0.5,
    )
    painted, _preview = render_coverage_stroke(
        before=before,
        dirty_rect=QRect(0, 0, 64, 64),
        segments=(paint,),
    )
    assert 126 <= int(painted[32, 32]) <= 129
    assert 0 < int(painted[32, 46]) < int(painted[32, 32])

    erase = replace(paint, operation=BrushOperation.ERASE, hardness=1.0)
    erased, _preview = render_coverage_stroke(
        before=painted,
        dirty_rect=QRect(0, 0, 64, 64),
        segments=(erase,),
    )
    assert 62 <= int(erased[32, 32]) <= 65


def test_editable_raster_paint_target_commits_one_undoable_stroke(
    qpane_with_mask,
) -> None:
    """Incremental color dabs must commit and replay as one exact scene edit."""
    qpane, _manager, _image_id = qpane_with_mask
    public_scene = qpane.currentScene()
    assert public_scene is not None
    layer_id = qpane.addEditableRasterLayer(
        _transparent_image(128, 96),
        placement=QRectF(0.0, 0.0, 128.0, 96.0),
        interaction=QPaneLayerInteractionPolicy(
            selectable=True,
            movable=True,
            pixel_editable=True,
        ),
        label="Paint",
    )
    assert layer_id is not None
    scene = qpane.sceneMutationCoordinator().active_scene()
    assert scene is not None
    painting = qpane.paintingCoordinator()
    assert painting.select_layer(scene.scene_id, layer_id)
    assert painting.set_color(QColor(240, 80, 30, 255))
    assert painting.set_preset(BrushPreset(size=24.0, hardness=0.65))

    before = qpane.editableRasterLayerImage(public_scene.scene_id, layer_id)
    assert before is not None
    assert painting.begin()
    for sequence, (start, end) in enumerate(
        (((16.0, 30.0), (48.0, 30.0)), ((48.0, 30.0), (92.0, 55.0)))
    ):
        assert painting.apply(
            BrushStrokeSegment(
                start=start,
                end=end,
                start_diameter=24.0,
                end_diameter=24.0,
                sequence=sequence,
            )
        )
    assert painting.commit()
    after = qpane.editableRasterLayerImage(public_scene.scene_id, layer_id)
    assert after is not None and after != before
    assert after.pixelColor(48, 30).alpha() > 0

    assert qpane.undoSceneEdit()
    undone = qpane.editableRasterLayerImage(public_scene.scene_id, layer_id)
    assert undone == before
    assert qpane.redoSceneEdit()
    redone = qpane.editableRasterLayerImage(public_scene.scene_id, layer_id)
    assert redone == after


def test_editable_raster_paint_honors_selection_and_expand_policy(
    qpane_with_mask,
) -> None:
    """Color paint must constrain softly and retain out-of-bounds layer pixels."""
    qpane, _manager, _image_id = qpane_with_mask
    public_scene = qpane.currentScene()
    assert public_scene is not None
    layer_id = qpane.addEditableRasterLayer(
        _transparent_image(32, 32),
        interaction=QPaneLayerInteractionPolicy(pixel_editable=True),
        extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
    )
    assert layer_id is not None
    selection = QImage(16, 16, QImage.Format_Grayscale8)
    selection.fill(128)
    assert qpane.setPixelSelection(selection, QRect(0, 0, 16, 16))
    scene = qpane.sceneMutationCoordinator().active_scene()
    assert scene is not None
    painting = qpane.paintingCoordinator()
    assert painting.select_layer(scene.scene_id, layer_id)
    assert painting.set_color(QColor(255, 0, 0, 255))
    assert painting.begin()
    assert painting.apply(BrushStrokeSegment.fixed((-5, 8), (24, 8), 12, False))
    assert painting.commit()

    state = qpane.rasterSurfaceState(public_scene.scene_id, layer_id)
    assert state is not None
    assert state.bounds.x() < 0
    image = qpane.editableRasterLayerImage(public_scene.scene_id, layer_id)
    assert image is not None
    selected_alpha = image.pixelColor(
        8 - state.bounds.x(), 8 - state.bounds.y()
    ).alpha()
    unselected_alpha = image.pixelColor(
        22 - state.bounds.x(), 8 - state.bounds.y()
    ).alpha()
    assert 126 <= selected_alpha <= 129
    assert unselected_alpha == 0


def test_pixel_selection_is_a_shared_soft_paint_target(qpane_with_mask) -> None:
    """Selection painting must preview live and commit through selection chronology."""
    qpane, _manager, _image_id = qpane_with_mask
    scene = qpane.sceneMutationCoordinator().active_scene()
    assert scene is not None
    painting = qpane.paintingCoordinator()
    assert painting.select_pixel_selection(scene.scene_id)
    assert painting.set_preset(BrushPreset(size=4.0, hardness=0.4, opacity=0.5))

    assert painting.begin()
    assert painting.apply(BrushStrokeSegment.fixed((2, 4), (6, 4), 4, False))
    preview = qpane.pixelSelectionState()
    assert preview is not None and preview.coverage is not None
    assert preview.bounds is not None
    preview_x = 4 - preview.bounds.x()
    preview_y = 4 - preview.bounds.y()
    preview_value = preview.coverage.pixelColor(preview_x, preview_y).red()
    assert 0 < preview_value < 255
    assert painting.commit()

    committed = qpane.pixelSelectionState()
    assert committed is not None and committed.coverage is not None
    assert qpane.undoSceneEdit()
    undone = qpane.pixelSelectionState()
    assert undone is not None and not undone.has_selection
    assert qpane.redoSceneEdit()
    restored = qpane.pixelSelectionState()
    assert restored is not None and restored.coverage == committed.coverage

    assert painting.begin()
    assert painting.apply(BrushStrokeSegment.fixed((4, 4), (4, 4), 3, True))
    erased = qpane.pixelSelectionState()
    assert erased is not None and erased.coverage is not None
    erased_x = 4 - erased.bounds.x()
    erased_y = 4 - erased.bounds.y()
    assert erased.coverage.pixelColor(erased_x, erased_y).red() < preview_value
    assert painting.cancel()
    cancelled = qpane.pixelSelectionState()
    assert cancelled is not None and cancelled.coverage == committed.coverage


def test_public_paint_target_and_empty_layer_contract(qpane_with_mask) -> None:
    """Hosts can create and configure a paint layer without private reach-through."""
    qpane, _manager, _image_id = qpane_with_mask
    scene = qpane.currentScene()
    assert scene is not None
    layer_id = qpane.createPaintLayer(
        label="Highlights",
        extent_policy=RasterExtentPolicy.FIXED,
    )
    assert layer_id is not None
    target = qpane.paintTargetState()
    assert target is not None
    assert target.scene_id == scene.scene_id
    assert target.kind is PaintTargetKind.LAYER
    assert target.layer_id == layer_id
    assert target.source_kind == "raster"

    preset = PublicBrushPreset(
        name="Soft pressure",
        size=13.0,
        hardness=0.25,
        opacity=0.7,
        flow=0.3,
        dynamics=PublicBrushDynamics(
            pressure_size=0.8,
            pressure_opacity=0.5,
            position_jitter=0.1,
        ),
    )
    assert qpane.setBrushPreset(preset)
    assert qpane.brushPreset() == preset
    assert qpane.setPaintColor(QColor(12, 80, 240, 190))
    assert qpane.paintColor() == QColor(12, 80, 240, 190)

    assert qpane.setPixelSelectionPaintTarget()
    selection_target = qpane.paintTargetState()
    assert selection_target is not None
    assert selection_target.kind is PaintTargetKind.PIXEL_SELECTION
    assert selection_target.layer_id is None
    assert selection_target.source_kind is None
    assert qpane.clearPaintTarget()
    assert qpane.paintTargetState() is None


def test_stale_layer_target_rolls_back_captured_transaction(qpane_with_mask) -> None:
    """Layer invalidation must cancel provisional pixels through the captured owner."""
    qpane, _manager, _image_id = qpane_with_mask
    layer_id = qpane.addEditableRasterLayer(
        _transparent_image(32, 32),
        interaction=QPaneLayerInteractionPolicy(pixel_editable=True),
    )
    assert layer_id is not None
    scene = qpane.sceneMutationCoordinator().active_scene()
    assert scene is not None
    layer = next(item for item in scene.layers if item.layer_id == layer_id)
    asset = qpane._editable_raster_assets.get(layer.source.raster_id)
    assert asset is not None
    before = asset.surface.snapshot_qimage()
    painting = qpane.paintingCoordinator()
    assert painting.select_layer(scene.scene_id, layer_id)
    assert painting.begin()
    assert painting.apply(BrushStrokeSegment.fixed((4, 4), (28, 28), 8, False))
    assert asset.surface.snapshot_qimage() != before

    composition_id = qpane.compositionService().current_composition_id()
    assert composition_id is not None
    assert qpane.compositionService().layers.remove_layer(composition_id, layer_id)
    assert painting.identity is None
    assert asset.surface.snapshot_qimage() == before
