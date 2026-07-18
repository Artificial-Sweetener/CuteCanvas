#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Tests for authoritative mask surface bounds and extent policy."""

from __future__ import annotations

from time import perf_counter

import numpy as np
import pytest
from PySide6.QtCore import QSize

from qpane.masks.surface import MaskSurface
from qpane.scene.raster import RasterBounds, RasterExtentPolicy


def test_blank_surface_defaults_to_fixed_origin_aligned_bounds() -> None:
    """Existing mask creation should retain finite image-sized semantics."""
    surface = MaskSurface.blank(QSize(7, 5))

    assert surface.bounds == RasterBounds(0, 0, 7, 5)
    assert surface.extent_policy is RasterExtentPolicy.FIXED
    assert surface.snapshot_array().shape == (5, 7)


def test_surface_reframe_preserves_pixels_by_layer_coordinate() -> None:
    """Padding on negative edges should not shift local pixel identity."""
    pixels = np.zeros((3, 4), dtype=np.uint8)
    pixels[1, 2] = 255
    surface = MaskSurface(pixels)

    assert surface.set_bounds(RasterBounds(-2, -1, 8, 6))

    expanded = surface.snapshot_array()
    assert surface.bounds == RasterBounds(-2, -1, 8, 6)
    assert expanded[2, 4] == 255
    assert np.count_nonzero(expanded) == 1


def test_surface_shrink_crops_only_pixels_outside_requested_bounds() -> None:
    """Explicit smaller bounds should retain the exact local intersection."""
    pixels = np.arange(20, dtype=np.uint8).reshape(4, 5)
    surface = MaskSurface(pixels, bounds=RasterBounds(-2, -1, 5, 4))

    assert surface.set_bounds(RasterBounds(-1, 0, 3, 2))

    np.testing.assert_array_equal(surface.snapshot_array(), pixels[1:3, 1:4])


def test_fixed_surface_reports_only_in_bounds_writable_intersection() -> None:
    """Fixed policy should clip writes without changing storage."""
    surface = MaskSurface.blank(QSize(8, 6))

    accepted = surface.ensure_writable(RasterBounds(-2, 2, 5, 3))

    assert accepted.writable == RasterBounds(0, 2, 3, 3)
    assert not accepted.expanded
    assert surface.bounds == RasterBounds(0, 0, 8, 6)


def test_expand_on_write_enlarges_every_edge_without_policy_side_effects() -> None:
    """Expandable policy should union requested local writes with storage."""
    surface = MaskSurface.blank(QSize(8, 6))
    original = surface.snapshot()
    assert surface.set_extent_policy(RasterExtentPolicy.EXPAND_ON_WRITE)
    assert surface.bounds == original.bounds
    np.testing.assert_array_equal(surface.snapshot_array(), original.pixels)

    accepted = surface.ensure_writable(RasterBounds(-2, -3, 13, 12))

    assert accepted.expanded
    assert accepted.writable == RasterBounds(-2, -3, 13, 12)
    assert surface.bounds == RasterBounds(-2, -3, 13, 12)


def test_surface_snapshot_restores_bounds_policy_and_pixels() -> None:
    """Structural snapshots should be sufficient for durable restoration."""
    surface = MaskSurface.blank(QSize(4, 3))
    surface.set_extent_policy(RasterExtentPolicy.EXPAND_ON_WRITE)
    surface.set_bounds(RasterBounds(-1, 2, 6, 5))
    surface.fill(127)
    snapshot = surface.snapshot()
    surface.set_extent_policy(RasterExtentPolicy.FIXED)
    surface.set_bounds(RasterBounds(0, 2, 2, 2))

    surface.replace_with_snapshot(snapshot)

    assert surface.bounds == RasterBounds(-1, 2, 6, 5)
    assert surface.extent_policy is RasterExtentPolicy.EXPAND_ON_WRITE
    assert np.all(surface.snapshot_array() == 127)


def test_storage_region_queries_copy_only_requested_pixels() -> None:
    """Storage reads should preserve values while honoring stride and bounds."""
    pixels = np.arange(36, dtype=np.uint8).reshape(6, 6)
    surface = MaskSurface(pixels, bounds=RasterBounds(-3, 4, 6, 6))

    sampled = surface.snapshot_storage_region(RasterBounds(1, 2, 4, 3), stride=2)

    np.testing.assert_array_equal(sampled, pixels[2:5:2, 1:5:2])
    assert surface.storage_value(4, 3) == int(pixels[3, 4])
    assert surface.storage_value(-1, 3) == 0
    assert surface.storage_value(6, 3) == 0


@pytest.mark.performance
def test_4k_surface_reframe_stays_within_interactive_growth_budget() -> None:
    """Padding a 4K surface should remain fast enough for first-edge brush input."""
    size = 4096
    surface = MaskSurface(
        np.zeros((size, size), dtype=np.uint8),
        extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
    )

    started = perf_counter()
    writable = surface.ensure_writable(RasterBounds(-32, -32, 64, 64))
    elapsed = perf_counter() - started

    assert elapsed < 1.0
    assert writable.expanded
    assert surface.bounds == RasterBounds(-32, -32, size + 32, size + 32)
