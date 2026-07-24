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
"""Deterministic shared-brush and editable-color target contracts."""

from __future__ import annotations

import math
import time
from dataclasses import replace

import numpy as np
import pytest
from cutecanvas import (
    BrushDynamics as PublicBrushDynamics,
)
from cutecanvas import (
    BrushPreset as PublicBrushPreset,
)
from cutecanvas import (
    CloneStampAlignment,
    CloneStampSampleMode,
    CloneStampTransform,
    LayerPolicy,
    PaintTargetKind,
    RasterExtentPolicy,
)
from cutecanvas.painting import (
    BrushCompositor,
    BrushDabEngine,
    BrushOperation,
    BrushPreset,
    BrushSourceCoordinateSession,
    BrushStrokeSegment,
    BrushStrokeSession,
    BrushTipCache,
)
from cutecanvas.painting.clone_compositor import CloneStampCompositor
from cutecanvas.painting.rendering import render_color_stroke, render_coverage_stroke
from cutecanvas.raster.color_surface import ColorRasterSurface
from cutecanvas.raster.revision_reader import RasterRevisionReader
from PySide6.QtCore import QPointF, QRect, QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QTransform
from qpane.sdk.scene import RasterBounds

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


def test_revision_reader_preserves_overwritten_tiles_without_copying_layer() -> None:
    """Clone sampling must retain touched source tiles, not the complete raster."""
    image = QImage(2048, 1024, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(12, 40, 90, 255))
    surface = ColorRasterSurface(image)
    reader = RasterRevisionReader(surface)
    changed = RasterBounds(128, 256, 128, 128)
    reader.preserve(changed)
    replacement = np.zeros((128, 128, 4), dtype=np.uint8)
    assert surface.restore_patch(changed, replacement)

    sampled = reader.read(RasterBounds(120, 248, 144, 144))

    assert np.all(sampled[8:136, 8:136, 3] == 255)
    assert reader.retained_bytes == 128 * 128 * 4
    assert reader.retained_bytes < image.sizeInBytes() // 16


def test_clone_compositor_samples_immutable_source_during_overlap() -> None:
    """Overlapping clone dabs must never feed their new pixels into the stroke."""
    pixels = np.zeros((32, 64, 4), dtype=np.uint8)
    pixels[:, :32, 0] = 30
    pixels[:, :32, 1] = 100
    pixels[:, :32, 2] = 220
    pixels[:, :32, 3] = 255
    image = QImage(
        pixels.data,
        64,
        32,
        pixels.strides[0],
        QImage.Format_ARGB32_Premultiplied,
    ).copy()
    surface = ColorRasterSurface(image)
    source = RasterRevisionReader(surface)
    compositor = CloneStampCompositor(BrushCompositor())
    dabs = BrushDabEngine().segment_dabs(
        BrushStrokeSegment(
            start=(20.0, 16.0),
            end=(48.0, 16.0),
            start_diameter=14.0,
            end_diameter=14.0,
            hardness=1.0,
            spacing=0.25,
        )
    )
    patch = RasterBounds(0, 0, 64, 32)
    source.preserve(patch)
    before = surface.capture_region(patch)
    after = compositor.render_dabs(
        before=before,
        source_pixels=source.sample_translated(patch, (-16.0, 0.0)),
        patch_bounds=patch,
        dabs=dabs,
    )

    assert np.all(after[16, 38:48, 3] == 255)
    assert np.all(after[16, 38:48, 2] == 220)
    assert np.all(after[16, 49:, 3] == 0)


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
        interaction=LayerPolicy(
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
    assert qpane.setSelectedLayer(public_scene.scene_id, layer_id)
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


def test_clone_stamp_selected_layer_is_revision_stable_and_undoable(
    qpane_with_mask,
) -> None:
    """One clone stroke samples its pre-edit layer and enters history atomically."""
    qpane, _manager, _image_id = qpane_with_mask
    qpane.createComposition(QRectF(0.0, 0.0, 64.0, 32.0), title="Clone revision")
    public_scene = qpane.currentScene()
    assert public_scene is not None
    image = _transparent_image(64, 32)
    for y in range(10, 23):
        for x in range(3, 16):
            image.setPixelColor(x, y, QColor(40, 120, 240, 255))
    layer_id = qpane.addEditableRasterLayer(
        image,
        interaction=LayerPolicy(selectable=True, pixel_editable=True),
        label="Clone target",
    )
    assert layer_id is not None
    scene = qpane.sceneMutationCoordinator().active_scene()
    assert scene is not None
    painting = qpane.paintingCoordinator()
    clone_stamp = qpane.cloneStampOperation()
    assert qpane.setSelectedLayer(public_scene.scene_id, layer_id)
    assert clone_stamp.set_source(QPointF(9.0, 16.0))
    assert painting.set_stroke_operation(clone_stamp)
    assert painting.set_preset(BrushPreset(size=10.0, hardness=1.0))

    before = qpane.editableRasterLayerImage(public_scene.scene_id, layer_id)
    assert before is not None
    assert painting.begin()
    assert painting.apply(
        BrushStrokeSegment.fixed((40.0, 16.0), (40.0, 16.0), 10.0, False)
    )
    assert painting.commit()
    after = qpane.editableRasterLayerImage(public_scene.scene_id, layer_id)

    assert after is not None
    assert after.pixelColor(40, 16) == QColor(40, 120, 240, 255)
    assert qpane.undoSceneEdit()
    assert qpane.editableRasterLayerImage(public_scene.scene_id, layer_id) == before
    assert qpane.redoSceneEdit()
    assert qpane.editableRasterLayerImage(public_scene.scene_id, layer_id) == after


def test_clone_stamp_source_matches_marker_with_nonzero_raster_origin(
    qapp,
    qpane_with_mask,
) -> None:
    """Selected-layer cloning must sample the scene point marked as its source."""
    qpane, _manager, _image_id = qpane_with_mask
    qpane.createComposition(QRectF(0.0, 0.0, 80.0, 40.0), title="Clone origin")
    public_scene = qpane.currentScene()
    assert public_scene is not None
    image = _transparent_image(64, 32)
    source_color = QColor(25, 140, 235, 255)
    image.setPixelColor(9, 16, source_color)
    layer_id = qpane.addEditableRasterLayer(
        image,
        interaction=LayerPolicy(selectable=True, pixel_editable=True),
        label="Offset clone target",
    )
    assert layer_id is not None
    completions: list[tuple[object, ...]] = []
    qpane.rasterBoundsRequestCompleted.connect(
        lambda *values: completions.append(tuple(values))
    )
    request_id = qpane.requestRasterBounds(
        public_scene.scene_id,
        layer_id,
        QRect(-7, -5, 72, 40),
    )
    assert request_id is not None
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and not completions:
        qapp.processEvents()
        time.sleep(0.005)
    assert completions and completions[-1][3] is True

    scene = qpane.sceneMutationCoordinator().active_scene()
    assert scene is not None
    painting = qpane.paintingCoordinator()
    clone_stamp = qpane.cloneStampOperation()
    assert qpane.setSelectedLayer(public_scene.scene_id, layer_id)
    assert clone_stamp.set_source(QPointF(9.0, 16.0))
    assert clone_stamp.source_scene_point() == QPointF(9.0, 16.0)
    assert painting.set_stroke_operation(clone_stamp)
    assert painting.set_preset(BrushPreset(size=1.0, hardness=1.0))

    assert painting.begin()
    assert painting.apply(
        BrushStrokeSegment.fixed((47.0, 21.0), (47.0, 21.0), 1.0, False)
    )
    assert painting.commit()
    result = qpane.editableRasterLayerImage(public_scene.scene_id, layer_id)

    assert result is not None
    assert result.pixelColor(47, 21) == source_color


def test_clone_stamp_source_anchor_stays_in_canvas_space_after_layer_transform(
    qpane_with_mask,
) -> None:
    """Rendered source identity changes without moving its canvas-space anchor."""
    qpane, _manager, _image_id = qpane_with_mask
    qpane.createComposition(QRectF(0.0, 0.0, 80.0, 40.0), title="Clone transform")
    public_scene = qpane.currentScene()
    assert public_scene is not None
    layer_id = qpane.addEditableRasterLayer(
        _transparent_image(64, 32),
        interaction=LayerPolicy(
            selectable=True,
            movable=True,
            pixel_editable=True,
        ),
        label="Transform-relative clone source",
    )
    assert layer_id is not None
    scene = qpane.sceneMutationCoordinator().active_scene()
    assert scene is not None
    clone_stamp = qpane.cloneStampOperation()
    assert qpane.setSelectedLayer(public_scene.scene_id, layer_id)
    assert clone_stamp.set_source(QPointF(9.0, 16.0))
    assert clone_stamp.source_scene_point() == QPointF(9.0, 16.0)

    assert qpane.setLayerTransform(
        public_scene.scene_id,
        layer_id,
        QTransform.fromTranslate(12.0, 7.0),
    )
    assert clone_stamp.source_scene_point() == QPointF(9.0, 16.0)
    assert clone_stamp.set_sample_mode(CloneStampSampleMode.VISIBLE_COMPOSITE)
    source = clone_stamp.state.source
    assert source is not None
    assert source.scene_point() == QPointF(9.0, 16.0)
    assert source.layer_id == layer_id
    assert clone_stamp.set_sample_mode(CloneStampSampleMode.ANCHORED_LAYER)
    restored_source = clone_stamp.state.source
    assert restored_source is not None
    assert restored_source.layer_id == layer_id
    assert restored_source.scene_point() == QPointF(9.0, 16.0)


def test_clone_stamp_visible_composite_samples_other_layers(
    qpane_with_mask,
) -> None:
    """Composite sampling follows visible layers through target affine geometry."""
    qpane, _manager, _image_id = qpane_with_mask
    public_scene = qpane.currentScene()
    assert public_scene is not None
    blue = QImage(8, 8, QImage.Format.Format_ARGB32_Premultiplied)
    blue.fill(QColor(20, 90, 210, 255))
    assert qpane.addEditableRasterLayer(blue, label="Composite source") is not None
    target_id = qpane.addEditableRasterLayer(
        _transparent_image(4, 4),
        placement=QRectF(0.0, 0.0, 8.0, 8.0),
        interaction=LayerPolicy(selectable=True, pixel_editable=True),
        label="Composite clone target",
    )
    assert target_id is not None
    scene = qpane.sceneMutationCoordinator().active_scene()
    assert scene is not None
    painting = qpane.paintingCoordinator()
    clone_stamp = qpane.cloneStampOperation()
    assert qpane.setSelectedLayer(public_scene.scene_id, target_id)
    assert clone_stamp.set_sample_mode(CloneStampSampleMode.VISIBLE_COMPOSITE)
    assert clone_stamp.set_source(QPointF(1.0, 1.0))
    assert painting.set_stroke_operation(clone_stamp)
    assert painting.set_preset(BrushPreset(size=1.0, hardness=1.0))

    assert painting.begin()
    assert painting.apply(BrushStrokeSegment.fixed((3.0, 3.0), (3.0, 3.0), 1.0, False))
    assert painting.commit()
    result = qpane.editableRasterLayerImage(public_scene.scene_id, target_id)

    assert result is not None
    assert result.pixelColor(3, 3) == QColor(20, 90, 210, 255)


def test_clone_stamp_alignment_changes_only_interstroke_source_mapping(
    qpane_with_mask,
) -> None:
    """Aligned strokes follow movement while unaligned strokes restart at source."""
    qpane, _manager, _image_id = qpane_with_mask
    qpane.createComposition(QRectF(0.0, 0.0, 80.0, 16.0), title="Clone alignment")
    public_scene = qpane.currentScene()
    assert public_scene is not None
    scene = qpane.sceneMutationCoordinator().active_scene()
    assert scene is not None
    painting = qpane.paintingCoordinator()
    clone_stamp = qpane.cloneStampOperation()
    assert painting.set_stroke_operation(clone_stamp)
    assert painting.set_preset(BrushPreset(size=1.0, hardness=1.0))
    assert clone_stamp.set_transform(CloneStampTransform(scale_x=2.0, scale_y=2.0))

    for alignment, expected in (
        (CloneStampAlignment.ALIGNED, QColor(30, 90, 230, 255)),
        (CloneStampAlignment.UNALIGNED, QColor(40, 210, 90, 255)),
    ):
        image = _transparent_image(80, 16)
        image.setPixelColor(10, 8, QColor(40, 210, 90, 255))
        image.setPixelColor(15, 8, QColor(30, 90, 230, 255))
        layer_id = qpane.addEditableRasterLayer(
            image,
            interaction=LayerPolicy(selectable=True, pixel_editable=True),
            label=alignment.value,
        )
        assert layer_id is not None
        assert qpane.setSelectedLayer(public_scene.scene_id, layer_id)
        clone_stamp.set_alignment(alignment)
        assert clone_stamp.state.alignment is alignment
        assert clone_stamp.set_source(QPointF(10.0, 8.0))

        for index, destination in enumerate((40.0, 50.0)):
            assert painting.begin()
            assert painting.apply(
                BrushStrokeSegment.fixed(
                    (destination, 8.0),
                    (destination, 8.0),
                    1.0,
                    False,
                )
            )
            expected_active_source = (
                QPointF(10.0 + index * 5.0, 8.0)
                if alignment is CloneStampAlignment.ALIGNED
                else QPointF(10.0, 8.0)
            )
            assert clone_stamp.source_scene_point() == expected_active_source
            assert painting.commit()
            assert clone_stamp.source_scene_point() == QPointF(10.0, 8.0)

        result = qpane.editableRasterLayerImage(
            public_scene.scene_id,
            layer_id,
        )
        assert result is not None
        actual = result.pixelColor(50, 8)
        assert abs(actual.red() - expected.red()) <= 2
        assert abs(actual.green() - expected.green()) <= 2
        assert abs(actual.blue() - expected.blue()) <= 2
        assert abs(actual.alpha() - expected.alpha()) <= 2
        assert clone_stamp.source_scene_point() == QPointF(10.0, 8.0)


def test_clone_stamp_affine_mapping_controls_source_motion_and_pixels(
    qpane_with_mask,
) -> None:
    """Rotation, reflection, and scale must drive one exact sampled mapping."""
    qpane, _manager, _image_id = qpane_with_mask
    qpane.createComposition(QRectF(0.0, 0.0, 100.0, 100.0), title="Affine clone")
    public_scene = qpane.currentScene()
    assert public_scene is not None
    source_color = QColor(230, 70, 25, 255)
    image = _transparent_image(100, 100)
    image.fill(QColor(5, 10, 15, 255))
    for y in range(35):
        for x in range(35):
            image.setPixelColor(x, y, QColor(0, 0, 0, 0))
    image.setPixelColor(50, 40, source_color)
    image.setPixelColor(40, 50, QColor(45, 210, 90, 255))
    image.setPixelColor(60, 50, QColor(80, 125, 235, 255))
    image.setPixelColor(70, 50, QColor(215, 55, 145, 255))
    layer_id = qpane.addEditableRasterLayer(
        image,
        interaction=LayerPolicy(selectable=True, pixel_editable=True),
        label="Affine clone target",
    )
    assert layer_id is not None
    assert qpane.setSelectedLayer(public_scene.scene_id, layer_id)
    assert qpane.setPaintTarget(public_scene.scene_id, layer_id)
    painting = qpane.paintingCoordinator()
    clone_stamp = qpane.cloneStampOperation()
    assert painting.set_stroke_operation(clone_stamp)
    assert painting.set_preset(BrushPreset(size=1.0, hardness=1.0))
    assert clone_stamp.set_source(QPointF(50.0, 50.0))

    cases = (
        (
            CloneStampTransform(rotation_degrees=90.0),
            QPointF(20.0, 10.0),
            QPointF(50.0, 40.0),
        ),
        (
            CloneStampTransform(rotation_degrees=180.0),
            QPointF(20.0, 10.0),
            QPointF(40.0, 50.0),
        ),
        (
            CloneStampTransform(mirror_horizontal=True),
            QPointF(20.0, 10.0),
            QPointF(40.0, 50.0),
        ),
        (
            CloneStampTransform(mirror_vertical=True),
            QPointF(10.0, 20.0),
            QPointF(50.0, 40.0),
        ),
        (
            CloneStampTransform(scale_x=2.0, scale_y=2.0),
            QPointF(30.0, 10.0),
            QPointF(60.0, 50.0),
        ),
        (
            CloneStampTransform(scale_x=0.5, scale_y=0.5),
            QPointF(20.0, 10.0),
            QPointF(70.0, 50.0),
        ),
        (
            CloneStampTransform(
                rotation_degrees=90.0,
                scale_x=2.0,
                scale_y=2.0,
                mirror_horizontal=True,
            ),
            QPointF(10.0, 30.0),
            QPointF(40.0, 50.0),
        ),
    )
    for transform, destination, expected_source in cases:
        clone_stamp.set_transform(transform)
        clone_stamp.set_source(QPointF(50.0, 50.0))
        assert painting.begin()
        assert painting.apply(
            BrushStrokeSegment.fixed((10.0, 10.0), (10.0, 10.0), 1.0, False)
        )
        assert painting.apply(
            BrushStrokeSegment.fixed(
                (10.0, 10.0),
                (destination.x(), destination.y()),
                1.0,
                False,
            )
        )
        actual_source = clone_stamp.source_scene_point()
        assert actual_source is not None
        assert abs(actual_source.x() - expected_source.x()) < 1e-9
        assert abs(actual_source.y() - expected_source.y()) < 1e-9
        assert painting.cancel()
        assert clone_stamp.source_scene_point() == QPointF(50.0, 50.0)

    arbitrary = CloneStampTransform(
        rotation_degrees=30.0,
        scale_x=2.0,
        scale_y=2.0,
    )
    assert clone_stamp.set_transform(arbitrary)
    assert painting.begin()
    assert painting.apply(
        BrushStrokeSegment.fixed((10.0, 10.0), (30.0, 10.0), 1.0, False)
    )
    arbitrary_source = clone_stamp.source_scene_point()
    assert arbitrary_source is not None
    assert abs(arbitrary_source.x() - (50.0 + 10.0 * math.cos(math.pi / 6))) < 1e-9
    assert abs(arbitrary_source.y() - 45.0) < 1e-9
    assert painting.cancel()

    for index, (transform, destination, expected_source) in enumerate(cases):
        start = QPointF(5.0, 5.0 + index * 10.0)
        delta = destination - QPointF(10.0, 10.0)
        rendered_at = start + delta
        expected = image.pixelColor(
            round(expected_source.x()),
            round(expected_source.y()),
        )
        assert clone_stamp.set_transform(transform)
        assert clone_stamp.set_source(QPointF(50.0, 50.0))
        assert painting.begin()
        assert painting.apply(
            BrushStrokeSegment.fixed(
                (start.x(), start.y()),
                (rendered_at.x(), rendered_at.y()),
                1.0,
                False,
            )
        )
        assert painting.commit()
        result = qpane.editableRasterLayerImage(public_scene.scene_id, layer_id)
        assert result is not None
        rendered = result.pixelColor(
            round(rendered_at.x()),
            round(rendered_at.y()),
        )
        assert abs(rendered.red() - expected.red()) <= 2
        assert abs(rendered.green() - expected.green()) <= 2
        assert abs(rendered.blue() - expected.blue()) <= 2
        assert abs(rendered.alpha() - expected.alpha()) <= 2


def test_clone_stamp_transform_rejects_unstable_configuration() -> None:
    """Public transform values must always compile to finite inverse sampling."""
    with pytest.raises(ValueError, match="scale_x"):
        CloneStampTransform(scale_x=0.0)
    with pytest.raises(ValueError, match="scale_y"):
        CloneStampTransform(scale_y=float("inf"))
    with pytest.raises(ValueError, match="rotation"):
        CloneStampTransform(rotation_degrees=float("nan"))
    with pytest.raises(TypeError, match="mirror_horizontal"):
        CloneStampTransform(mirror_horizontal=1)  # type: ignore[arg-type]


def test_clone_stamp_transform_change_is_deferred_until_the_next_stroke(
    qpane_with_mask,
) -> None:
    """Host configuration changes must not disturb one frozen stroke mapping."""
    qpane, _manager, _image_id = qpane_with_mask
    qpane.createComposition(QRectF(0.0, 0.0, 100.0, 100.0))
    public_scene = qpane.currentScene()
    assert public_scene is not None
    image = _transparent_image(100, 100)
    painter = QPainter(image)
    painter.fillRect(QRect(35, 35, 35, 35), QColor(80, 120, 180, 255))
    painter.end()
    layer_id = qpane.addEditableRasterLayer(
        image,
        interaction=LayerPolicy(selectable=True, pixel_editable=True),
    )
    assert layer_id is not None
    assert qpane.setSelectedLayer(public_scene.scene_id, layer_id)
    assert qpane.setPaintTarget(public_scene.scene_id, layer_id)
    painting = qpane.paintingCoordinator()
    clone_stamp = qpane.cloneStampOperation()
    assert painting.set_stroke_operation(clone_stamp)
    assert painting.set_preset(BrushPreset(size=1.0, hardness=1.0))
    assert clone_stamp.set_source(QPointF(50.0, 50.0))

    assert painting.begin()
    assert painting.apply(
        BrushStrokeSegment.fixed((10.0, 10.0), (10.0, 10.0), 1.0, False)
    )
    assert clone_stamp.set_transform(CloneStampTransform(rotation_degrees=90.0))
    assert painting.apply(
        BrushStrokeSegment.fixed((10.0, 10.0), (20.0, 10.0), 1.0, False)
    )
    assert clone_stamp.source_scene_point() == QPointF(60.0, 50.0)
    assert painting.commit()
    assert clone_stamp.source_scene_point() == QPointF(50.0, 50.0)

    assert painting.begin()
    assert painting.apply(
        BrushStrokeSegment.fixed((10.0, 20.0), (20.0, 20.0), 1.0, False)
    )
    assert clone_stamp.source_scene_point() == QPointF(50.0, 40.0)
    assert painting.cancel()


def test_clone_stamp_reselecting_same_source_resets_aligned_mapping(
    qpane_with_mask,
) -> None:
    """Explicit source selection must reset retained alignment even at one point."""
    qpane, _manager, _image_id = qpane_with_mask
    qpane.createComposition(QRectF(0.0, 0.0, 80.0, 16.0), title="Clone reset")
    public_scene = qpane.currentScene()
    assert public_scene is not None
    scene = qpane.sceneMutationCoordinator().active_scene()
    assert scene is not None
    image = _transparent_image(80, 16)
    original = QColor(40, 210, 90, 255)
    shifted = QColor(30, 90, 230, 255)
    image.setPixelColor(10, 8, original)
    image.setPixelColor(20, 8, shifted)
    layer_id = qpane.addEditableRasterLayer(
        image,
        interaction=LayerPolicy(selectable=True, pixel_editable=True),
        label="Aligned source reset",
    )
    assert layer_id is not None
    painting = qpane.paintingCoordinator()
    clone_stamp = qpane.cloneStampOperation()
    assert qpane.setSelectedLayer(public_scene.scene_id, layer_id)
    assert clone_stamp.set_alignment(CloneStampAlignment.ALIGNED) is False
    assert clone_stamp.set_source(QPointF(10.0, 8.0))
    assert painting.set_stroke_operation(clone_stamp)
    assert painting.set_preset(BrushPreset(size=1.0, hardness=1.0))

    for destination in (40.0, 50.0):
        assert painting.begin()
        assert painting.apply(
            BrushStrokeSegment.fixed(
                (destination, 8.0),
                (destination, 8.0),
                1.0,
                False,
            )
        )
        assert painting.commit()
    assert clone_stamp.source_scene_point() == QPointF(10.0, 8.0)

    assert clone_stamp.set_source(QPointF(10.0, 8.0))
    assert clone_stamp.source_scene_point() == QPointF(10.0, 8.0)
    assert painting.begin()
    assert painting.apply(
        BrushStrokeSegment.fixed((60.0, 8.0), (60.0, 8.0), 1.0, False)
    )
    assert painting.commit()
    result = qpane.editableRasterLayerImage(public_scene.scene_id, layer_id)

    assert result is not None
    assert result.pixelColor(60, 8) == original


def test_editable_raster_paint_honors_selection_and_expand_policy(
    qpane_with_mask,
) -> None:
    """Color paint must constrain softly and retain out-of-bounds layer pixels."""
    qpane, _manager, _image_id = qpane_with_mask
    public_scene = qpane.currentScene()
    assert public_scene is not None
    layer_id = qpane.addEditableRasterLayer(
        _transparent_image(32, 32),
        interaction=LayerPolicy(pixel_editable=True),
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
        interaction=LayerPolicy(pixel_editable=True),
    )
    assert layer_id is not None
    scene = qpane.sceneMutationCoordinator().active_scene()
    assert scene is not None
    layer = next(item for item in scene.layers if item.layer_id == layer_id)
    asset = qpane._editable_raster_assets.get(layer.source.resource_id)
    assert asset is not None
    before = asset.surface.snapshot_qimage()
    painting = qpane.paintingCoordinator()
    assert painting.select_layer(scene.scene_id, layer_id)
    assert painting.begin()
    assert painting.apply(BrushStrokeSegment.fixed((4, 4), (28, 28), 8, False))
    assert asset.surface.snapshot_qimage() != before

    composition_id = qpane.viewSession().active_composition_id
    assert composition_id is not None
    assert qpane.compositionService().layers.remove_layer(composition_id, layer_id)
    assert painting.identity is None
    assert asset.surface.snapshot_qimage() == before
