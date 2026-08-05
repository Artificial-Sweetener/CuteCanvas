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
"""Exact and cancellation contracts for bounded grayscale coverage filters."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest
from cutecanvas.coverage import (
    CoverageFilterCancelledError,
    dilate_coverage,
    erode_coverage,
    feather_coverage,
)

from tests.harness.timing import completion_clock


@pytest.mark.parametrize("radius", (0, 1, 2, 5))
def test_dilation_matches_independent_square_reference(radius: int) -> None:
    """Dilation must preserve soft values and use zero coverage beyond bounds."""
    source = np.array(
        [
            [0, 0, 0, 0, 0, 0, 0],
            [0, 20, 80, 0, 0, 0, 0],
            [0, 0, 160, 0, 0, 240, 0],
            [0, 0, 0, 0, 0, 0, 0],
        ],
        dtype=np.uint8,
    )

    assert np.array_equal(
        dilate_coverage(source, radius),
        _reference_extreme(source, radius, maximum=True),
    )


@pytest.mark.parametrize("radius", (0, 1, 2, 5))
def test_erosion_matches_independent_square_reference(radius: int) -> None:
    """Erosion must contract soft coverage against zero beyond storage."""
    source = np.array(
        [
            [255, 255, 255, 255, 255, 255],
            [255, 220, 180, 160, 140, 255],
            [255, 200, 120, 80, 60, 255],
            [255, 255, 255, 255, 255, 255],
        ],
        dtype=np.uint8,
    )

    assert np.array_equal(
        erode_coverage(source, radius),
        _reference_extreme(source, radius, maximum=False),
    )


def test_feather_is_symmetric_and_conserves_a_soft_center() -> None:
    """Feathering must create a symmetric soft edge without binary conversion."""
    source = np.zeros((31, 31), dtype=np.uint8)
    source[10:21, 10:21] = 200

    result = feather_coverage(source, 3.5)

    assert np.array_equal(result, result[::-1, :])
    assert np.array_equal(result, result[:, ::-1])
    assert 0 < result[8, 15] < result[10, 15] < 200
    assert result[15, 15] > result[10, 15]


@pytest.mark.parametrize(
    ("operation", "radius"),
    (
        (dilate_coverage, -1),
        (dilate_coverage, 1.5),
        (erode_coverage, -2),
        (feather_coverage, -0.5),
        (feather_coverage, float("nan")),
    ),
)
def test_filters_reject_invalid_radii(
    operation: Callable[..., np.ndarray],
    radius: float,
) -> None:
    """Invalid radii must fail before allocating filter products."""
    with pytest.raises(ValueError):
        operation(np.zeros((3, 3), dtype=np.uint8), radius)


def test_filters_cancel_between_bounded_products() -> None:
    """Long-running filter work must terminate cooperatively without a result."""
    checks = 0

    def cancelled() -> bool:
        """Cancel after the first bounded work band."""
        nonlocal checks
        checks += 1
        return checks > 1

    with pytest.raises(CoverageFilterCancelledError):
        dilate_coverage(
            np.full((256, 256), 255, dtype=np.uint8),
            12,
            cancelled=cancelled,
        )


def test_large_coverage_filters_keep_linear_time_products_bounded() -> None:
    """Production-size filters must avoid radius-multiplied neighborhood scans."""
    source = np.zeros((1024, 1024), dtype=np.uint8)
    source[256:768, 256:768] = 255

    started = completion_clock()
    expanded = dilate_coverage(source, 64)
    contracted = erode_coverage(source, 64)
    feathered = feather_coverage(source, 32.0)
    elapsed = completion_clock() - started

    assert expanded.shape == source.shape
    assert contracted.shape == source.shape
    assert feathered.shape == source.shape
    assert elapsed < 5.0


@pytest.mark.parametrize(
    "source",
    (
        np.zeros((2, 2, 1), dtype=np.uint8),
        np.zeros((2, 2), dtype=np.float32),
    ),
)
def test_filters_reject_noncanonical_coverage(source: np.ndarray) -> None:
    """Filters must reject ambiguous array shape and coverage precision."""
    with pytest.raises(ValueError):
        dilate_coverage(source, 1)


def _reference_extreme(
    source: np.ndarray,
    radius: int,
    *,
    maximum: bool,
) -> np.ndarray:
    """Return an intentionally simple neighborhood reference product."""
    result = np.zeros_like(source)
    for y in range(source.shape[0]):
        for x in range(source.shape[1]):
            values: list[int] = []
            for sample_y in range(y - radius, y + radius + 1):
                for sample_x in range(x - radius, x + radius + 1):
                    values.append(
                        int(source[sample_y, sample_x])
                        if (
                            0 <= sample_y < source.shape[0]
                            and 0 <= sample_x < source.shape[1]
                        )
                        else 0
                    )
            result[y, x] = max(values) if maximum else min(values)
    return result
