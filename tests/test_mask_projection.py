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
"""Tests for viewport-independent mask-to-canvas projection."""

from __future__ import annotations

import uuid
from time import perf_counter

import numpy as np
import pytest
from cutecanvas import RasterExtentPolicy
from cutecanvas.coverage import CoverageSnapshot
from cutecanvas.masks.mask import MaskAssetStore
from cutecanvas.masks.projection import (
    MaskCanvasProjectionService,
    project_mask_snapshot,
)
from cutecanvas.resources import ProjectResourceReference, ProjectResourceStore
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
from qpane.scene.affine import LayerTransform
from qpane.scene.model import (
    LayerDescriptor,
    LayerKind,
    LayerPlacement,
    SceneDescriptor,
    SceneKind,
)
from qpane.scene.raster import RasterBounds


def _descriptor(
    bounds: RasterBounds,
    transform: LayerTransform,
) -> LayerDescriptor:
    """Return one mask descriptor with explicit local bounds and transform."""
    scene_id = uuid.uuid4()
    mask_id = uuid.uuid4()
    return LayerDescriptor(
        scene_id=scene_id,
        layer_id=uuid.uuid4(),
        kind=LayerKind.MASK,
        source=ProjectResourceReference(mask_id),
        placement=transform.map_bounds(bounds),
        raster_bounds=bounds,
        transform=transform,
    )


def test_projection_clips_negative_and_positive_off_canvas_pixels() -> None:
    """Only the authoring pixels intersecting canvas bounds should be exported."""
    bounds = RasterBounds(-2, -1, 8, 6)
    pixels = np.zeros((6, 8), dtype=np.uint8)
    pixels[1, 2] = 10
    pixels[2, 3] = 20
    pixels[5, 7] = 30
    snapshot = CoverageSnapshot(
        bounds,
        RasterExtentPolicy.EXPAND_ON_WRITE,
        pixels,
    )
    layer = _descriptor(bounds, LayerTransform())

    projected = project_mask_snapshot(
        snapshot,
        layer=layer,
        canvas_x=0.0,
        canvas_y=0.0,
        canvas_width=4,
        canvas_height=4,
    )

    assert projected.shape == (4, 4)
    assert projected[0, 0] == 10
    assert projected[1, 1] == 20
    assert projected.sum() == 30


def test_projection_applies_layer_translation_before_canvas_clipping() -> None:
    """Movement should alter exported visibility without mutating authoring pixels."""
    bounds = RasterBounds(0, 0, 4, 4)
    pixels = np.zeros((4, 4), dtype=np.uint8)
    pixels[1, 1] = 255
    snapshot = CoverageSnapshot(bounds, RasterExtentPolicy.FIXED, pixels)
    transform = LayerTransform(dx=2.0, dy=-1.0)
    layer = _descriptor(bounds, transform)

    projected = project_mask_snapshot(
        snapshot,
        layer=layer,
        canvas_x=0.0,
        canvas_y=0.0,
        canvas_width=4,
        canvas_height=4,
    )

    assert projected[0, 3] == 255
    assert projected.sum() == 255


def test_generated_canvas_mask_uses_infinite_default_and_obeys_fixed_policy() -> None:
    """Mask defaults expand through movement while explicit fixed storage clips."""
    assets = MaskAssetStore(ProjectResourceStore())
    mask_id = assets.create_mask(QImage(QSize(4, 4), QImage.Format_Grayscale8))
    scene_id = uuid.uuid4()
    bounds = RasterBounds(0, 0, 4, 4)
    transform = LayerTransform(dx=2.0)
    layer = LayerDescriptor(
        scene_id=scene_id,
        layer_id=uuid.uuid4(),
        kind=LayerKind.MASK,
        source=ProjectResourceReference(mask_id),
        placement=transform.map_bounds(bounds),
        raster_bounds=bounds,
        transform=transform,
    )
    scene = SceneDescriptor(
        scene_id=scene_id,
        kind=SceneKind.EXPLICIT,
        bounds=LayerPlacement(0.0, 0.0, 4.0, 4.0),
        layers=(layer,),
    )
    projection = MaskCanvasProjectionService(
        assets=assets,
        active_scene=lambda: scene,
    )
    incoming = np.zeros((4, 4), dtype=np.uint8)
    incoming[1, 0] = 255

    surface = assets.get_surface(mask_id)
    assert surface is not None
    expanded = projection.combine_canvas_mask(mask_id, incoming, erase=False)
    assert expanded is not None
    assert expanded.bounds == RasterBounds(-2, 0, 6, 4)
    assert expanded.pixels[1, 0] == 255

    surface.set_extent_policy(RasterExtentPolicy.FIXED)
    assert projection.combine_canvas_mask(mask_id, incoming, erase=False) is None


@pytest.mark.performance
def test_4k_projection_stays_within_interactive_worker_budget() -> None:
    """A 4K viewport-independent export should retain a generous CPU budget."""
    size = 4096
    bounds = RasterBounds(0, 0, size, size)
    pixels = np.zeros((size, size), dtype=np.uint8)
    pixels[2048, 2048] = 255
    snapshot = CoverageSnapshot(
        bounds,
        RasterExtentPolicy.EXPAND_ON_WRITE,
        pixels,
    )
    layer = _descriptor(
        bounds,
        LayerTransform(dx=12.0, dy=-8.0),
    )

    started = perf_counter()
    projected = project_mask_snapshot(
        snapshot,
        layer=layer,
        canvas_x=0.0,
        canvas_y=0.0,
        canvas_width=size,
        canvas_height=size,
    )
    elapsed = perf_counter() - started

    assert elapsed < 2.0
    assert projected[2040, 2060] == 255
