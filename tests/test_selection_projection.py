#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Adversarial scene-to-layer coverage projection checks."""

from __future__ import annotations

import random
import uuid

import numpy as np

from qpane.coverage import CoverageSnapshot
from qpane.editor.selection_projection import (
    LayerSelectionProjectionCache,
    translated_coverage_within,
)
from qpane.scene.raster import LayerTransform, RasterBounds, RasterExtentPolicy
from qpane.selection import LayerCoverageProjector


def _coverage(bounds: RasterBounds, pixels: np.ndarray) -> CoverageSnapshot:
    """Return detached expanding coverage for projection tests."""
    return CoverageSnapshot(
        bounds=bounds,
        extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
        pixels=pixels,
    )


def test_project_to_layer_matches_aligned_rectangle_oracle_across_affines() -> None:
    """Aligned selections must map exactly across translations, scales, and origins."""
    projector = LayerCoverageProjector()
    randomizer = random.Random(20260718)
    scales = (0.5, 1.0, 2.0, 4.0)
    for _case in range(160):
        scale_x = randomizer.choice(scales)
        scale_y = randomizer.choice(scales)
        layer_x = randomizer.randint(-40, 20)
        layer_y = randomizer.randint(-40, 20)
        layer_width = randomizer.randint(12, 80)
        layer_height = randomizer.randint(12, 80)
        local_width = randomizer.randint(2, max(2, layer_width // 3))
        local_height = randomizer.randint(2, max(2, layer_height // 3))
        local_x = randomizer.randint(layer_x, layer_x + layer_width - local_width)
        local_y = randomizer.randint(layer_y, layer_y + layer_height - local_height)
        if scale_x == 0.5:
            local_x += local_x % 2
            local_width -= local_width % 2
        if scale_y == 0.5:
            local_y += local_y % 2
            local_height -= local_height % 2
        local_width = max(2, local_width)
        local_height = max(2, local_height)
        layer_bounds = RasterBounds(layer_x, layer_y, layer_width, layer_height)
        transform = LayerTransform(
            scale_x=scale_x,
            scale_y=scale_y,
            translate_x=float(randomizer.randint(-100, 100)),
            translate_y=float(randomizer.randint(-100, 100)),
        )
        scene_x = round(local_x * scale_x + transform.translate_x)
        scene_y = round(local_y * scale_y + transform.translate_y)
        scene_width = round(local_width * scale_x)
        scene_height = round(local_height * scale_y)
        scene = _coverage(
            RasterBounds(scene_x, scene_y, scene_width, scene_height),
            np.full((scene_height, scene_width), 255, dtype=np.uint8),
        )

        projected = projector.project_to_layer(scene, transform, layer_bounds)

        assert projected is not None
        assert projected.bounds == RasterBounds(
            local_x,
            local_y,
            local_width,
            local_height,
        )
        assert np.all(projected.pixels == 255)


def test_integer_translation_round_trip_preserves_random_soft_coverage() -> None:
    """Source-neutral projection must preserve arbitrary soft bytes at unit scale."""
    projector = LayerCoverageProjector()
    randomizer = np.random.default_rng(20260718)
    for index in range(64):
        width = int(randomizer.integers(1, 48))
        height = int(randomizer.integers(1, 48))
        bounds = RasterBounds(
            int(randomizer.integers(-30, 31)),
            int(randomizer.integers(-30, 31)),
            width,
            height,
        )
        pixels = randomizer.integers(
            1,
            256,
            size=(height, width),
            dtype=np.uint8,
        )
        source = _coverage(bounds, pixels)
        transform = LayerTransform(
            translate_x=float(index - 32),
            translate_y=float(40 - index),
        )

        scene = projector.project(source, transform)
        assert scene is not None
        restored = projector.project_to_layer(scene, transform, bounds)

        assert restored is not None
        assert restored.bounds == bounds
        assert np.array_equal(restored.pixels, pixels)
        assert scene.pixels is source.pixels
        assert restored.pixels is source.pixels


def test_exact_layer_projection_cache_is_revision_and_transform_scoped() -> None:
    """Derived local coverage must never survive authoritative identity changes."""
    cache = LayerSelectionProjectionCache()
    scene_id = uuid.uuid4()
    layer_id = uuid.uuid4()
    transform = LayerTransform(scale_x=2.0, scale_y=3.0)
    coverage = _coverage(RasterBounds(4, 5, 2, 1), np.array([[64, 255]]))
    cache.remember(
        scene_id=scene_id,
        layer_id=layer_id,
        selection_revision=7,
        transform=transform,
        coverage=coverage,
    )

    assert (
        cache.resolve(
            scene_id=scene_id,
            layer_id=layer_id,
            selection_revision=7,
            transform=transform,
        )
        is coverage
    )
    assert (
        cache.resolve(
            scene_id=scene_id,
            layer_id=layer_id,
            selection_revision=8,
            transform=transform,
        )
        is None
    )
    assert (
        cache.resolve(
            scene_id=scene_id,
            layer_id=layer_id,
            selection_revision=7,
            transform=LayerTransform(scale_x=2.0, scale_y=2.0),
        )
        is None
    )


def test_translated_exact_projection_clips_pixels_with_fixed_raster_bounds() -> None:
    """Cached post-move coverage must match pixels retained by a fixed raster."""
    coverage = _coverage(
        RasterBounds(1, 1, 3, 2),
        np.array([[10, 20, 30], [40, 50, 60]], dtype=np.uint8),
    )

    translated = translated_coverage_within(
        coverage,
        2,
        1,
        RasterBounds(0, 0, 5, 4),
    )

    assert translated.bounds == RasterBounds(3, 2, 2, 2)
    np.testing.assert_array_equal(
        translated.pixels,
        np.array([[10, 20], [40, 50]], dtype=np.uint8),
    )
