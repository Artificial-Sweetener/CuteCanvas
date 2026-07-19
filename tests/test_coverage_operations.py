#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Tests for shared grayscale coverage combination semantics."""

from __future__ import annotations

import numpy as np
import pytest

from qpane.coverage import (
    CoverageCombineMode,
    CoverageSnapshot,
    combine_coverage,
)
from qpane.scene.raster import RasterBounds, RasterExtentPolicy


@pytest.mark.parametrize(
    ("mode", "expected"),
    (
        (CoverageCombineMode.REPLACE, [0, 255, 128, 64]),
        (CoverageCombineMode.ADD, [0, 255, 192, 160]),
        (CoverageCombineMode.SUBTRACT, [0, 0, 64, 96]),
        (CoverageCombineMode.INTERSECT, [0, 255, 64, 32]),
    ),
)
def test_coverage_algebra_preserves_soft_values(
    mode: CoverageCombineMode,
    expected: list[int],
) -> None:
    """Every operation should retain proportional intermediate coverage."""
    existing = np.array([[0, 255, 128, 128]], dtype=np.uint8)
    incoming = np.array([[0, 255, 128, 64]], dtype=np.uint8)

    result = combine_coverage(existing, incoming, mode)

    np.testing.assert_array_equal(result, np.array([expected], dtype=np.uint8))


def test_binary_operations_match_existing_mask_semantics() -> None:
    """Hard masks must retain established boolean union and erase behavior."""
    existing = np.array([[0, 0, 255, 255]], dtype=np.uint8)
    incoming = np.array([[0, 255, 0, 255]], dtype=np.uint8)

    added = combine_coverage(existing, incoming, CoverageCombineMode.ADD)
    subtracted = combine_coverage(existing, incoming, CoverageCombineMode.SUBTRACT)

    np.testing.assert_array_equal(added, np.array([[0, 255, 255, 255]], np.uint8))
    np.testing.assert_array_equal(subtracted, np.array([[0, 0, 255, 0]], np.uint8))


def test_coverage_combination_rejects_mismatched_shapes() -> None:
    """Callers must project coverage into one coordinate extent first."""
    with pytest.raises(ValueError, match="matching shapes"):
        combine_coverage(
            np.zeros((2, 2), dtype=np.uint8),
            np.zeros((3, 2), dtype=np.uint8),
            CoverageCombineMode.ADD,
        )


def test_replace_returns_detached_pixels_without_mutating_operands() -> None:
    """Coverage algebra may reuse canonical inputs internally but never alias output."""
    existing = np.array([[20, 40]], dtype=np.uint8)
    incoming = np.array([[80, 160]], dtype=np.uint8)

    result = combine_coverage(existing, incoming, CoverageCombineMode.REPLACE)
    result[0, 0] = 0

    np.testing.assert_array_equal(existing, np.array([[20, 40]], dtype=np.uint8))
    np.testing.assert_array_equal(incoming, np.array([[80, 160]], dtype=np.uint8))


def test_translated_snapshot_reuses_immutable_coverage_storage() -> None:
    """Coordinate-only translation must not copy a potentially large pixel field."""
    snapshot = CoverageSnapshot(
        RasterBounds(10, 20, 1000, 1000),
        RasterExtentPolicy.EXPAND_ON_WRITE,
        np.full((1000, 1000), 255, dtype=np.uint8),
    )

    translated = snapshot.translated(30, -5)

    assert translated.bounds == RasterBounds(40, 15, 1000, 1000)
    assert translated.pixels is snapshot.pixels
    assert not snapshot.pixels.flags.writeable
