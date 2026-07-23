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
"""Characterize exact NumPy mask morphology and resize semantics."""

from __future__ import annotations

from collections import deque
from time import process_time

import numpy as np
import pytest
from cutecanvas.masks.image_ops import (
    adjust_connected_component,
    outer_mask_border,
    resize_mask_nearest,
)


@pytest.mark.parametrize("grow", (False, True))
def test_component_adjustment_matches_independent_reference(grow: bool) -> None:
    """Random components retain 8-connectivity and cross morphology semantics."""
    random = np.random.default_rng(20260718)
    for height, width in ((1, 1), (3, 7), (17, 13), (32, 31)):
        for _ in range(20):
            mask = np.where(random.random((height, width)) > 0.68, 255, 0).astype(
                np.uint8
            )
            foreground = np.argwhere(mask != 0)
            if not foreground.size:
                continue
            y, x = foreground[random.integers(len(foreground))]
            actual = adjust_connected_component(mask, x=int(x), y=int(y), grow=grow)
            expected = _reference_adjust(mask, x=int(x), y=int(y), grow=grow)
            assert actual is not None
            np.testing.assert_array_equal(actual, expected)


def test_outer_border_matches_square_dilation_reference() -> None:
    """Border pixels are the exact one-pixel exterior of a square dilation."""
    random = np.random.default_rng(42)
    for shape in ((1, 1), (2, 7), (19, 23)):
        mask = np.where(random.random(shape) > 0.7, 255, 0).astype(np.uint8)
        padded = np.pad(mask, 1)
        dilated = np.zeros_like(mask)
        for y_offset in range(3):
            for x_offset in range(3):
                np.maximum(
                    dilated,
                    padded[
                        y_offset : y_offset + shape[0],
                        x_offset : x_offset + shape[1],
                    ],
                    out=dilated,
                )
        np.testing.assert_array_equal(
            outer_mask_border(mask),
            dilated - mask,
        )


def test_nearest_resize_uses_legacy_floor_sampling() -> None:
    """Every destination coordinate samples floor(index * source / target)."""
    source = np.arange(5 * 7, dtype=np.uint8).reshape(5, 7)
    for target in ((1, 1), (3, 11), (12, 4), (5, 7)):
        source_y = np.floor(np.arange(target[0]) * 5 / target[0]).astype(int)
        source_x = np.floor(np.arange(target[1]) * 7 / target[1]).astype(int)
        expected = source[source_y[:, None], source_x[None, :]]
        np.testing.assert_array_equal(resize_mask_nearest(source, target), expected)


def test_4k_mask_operations_stay_within_background_work_bound() -> None:
    """Representative 4K operations avoid catastrophic latency regressions."""
    mask = np.zeros((4096, 4096), dtype=np.uint8)
    mask[512:3584, 512:3584] = 255

    operations = (
        ("border", lambda: outer_mask_border(mask)),
        ("resize", lambda: resize_mask_nearest(mask, (2048, 2048))),
        (
            "grow",
            lambda: adjust_connected_component(mask, x=2048, y=2048, grow=True),
        ),
        (
            "shrink",
            lambda: adjust_connected_component(mask, x=2048, y=2048, grow=False),
        ),
    )
    for name, operation in operations:
        started = process_time()
        result = operation()
        duration = process_time() - started
        assert result is not None
        assert duration < 1.0, f"{name} took {duration * 1000.0:.1f} ms"


def _reference_adjust(
    mask: np.ndarray,
    *,
    x: int,
    y: int,
    grow: bool,
) -> np.ndarray:
    """Return a deliberately simple reference implementation."""
    height, width = mask.shape
    component = np.zeros_like(mask, dtype=bool)
    pending = deque([(x, y)])
    component[y, x] = True
    while pending:
        current_x, current_y = pending.popleft()
        for neighbor_y in range(max(0, current_y - 1), min(height, current_y + 2)):
            for neighbor_x in range(max(0, current_x - 1), min(width, current_x + 2)):
                if (
                    mask[neighbor_y, neighbor_x]
                    and not component[neighbor_y, neighbor_x]
                ):
                    component[neighbor_y, neighbor_x] = True
                    pending.append((neighbor_x, neighbor_y))
    adjusted = component.copy()
    if grow:
        adjusted[1:, :] |= component[:-1, :]
        adjusted[:-1, :] |= component[1:, :]
        adjusted[:, 1:] |= component[:, :-1]
        adjusted[:, :-1] |= component[:, 1:]
    else:
        adjusted.fill(False)
        for component_y, component_x in np.argwhere(component):
            neighbors = (
                (component_x, component_y),
                (component_x - 1, component_y),
                (component_x + 1, component_y),
                (component_x, component_y - 1),
                (component_x, component_y + 1),
            )
            adjusted[component_y, component_x] = all(
                neighbor_x < 0
                or neighbor_y < 0
                or neighbor_x >= width
                or neighbor_y >= height
                or component[neighbor_y, neighbor_x]
                for neighbor_x, neighbor_y in neighbors
            )
    result = mask.copy()
    result[component] = 0
    result[adjusted] = 255
    return result
