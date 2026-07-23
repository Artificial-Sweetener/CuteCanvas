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

"""Focused NumPy image operations for grayscale mask pixels."""

from __future__ import annotations

import numpy as np


def resize_mask_nearest(mask: np.ndarray, target_shape: tuple[int, int]) -> np.ndarray:
    """Resize a mask with the nearest-neighbor sampling used by mask merging."""
    target_height, target_width = target_shape
    if target_height < 0 or target_width < 0:
        raise ValueError("target mask dimensions must be non-negative")
    source = _grayscale_array(mask)
    if source.shape == target_shape:
        return np.array(source, copy=True, order="C")
    if target_height == 0 or target_width == 0:
        return np.zeros(target_shape, dtype=np.uint8)
    source_height, source_width = source.shape
    if source_height == 0 or source_width == 0:
        return np.zeros(target_shape, dtype=np.uint8)
    source_y = np.floor(
        np.arange(target_height, dtype=np.float64) * source_height / target_height
    ).astype(np.intp)
    source_x = np.floor(
        np.arange(target_width, dtype=np.float64) * source_width / target_width
    ).astype(np.intp)
    return np.ascontiguousarray(source[source_y[:, None], source_x[None, :]])


def adjust_connected_component(
    mask: np.ndarray,
    *,
    x: int,
    y: int,
    grow: bool,
) -> np.ndarray | None:
    """Grow or shrink the 8-connected component containing one pixel."""
    working = np.array(_grayscale_array(mask), copy=True, order="C")
    height, width = working.shape
    if x < 0 or y < 0 or x >= width or y >= height or working[y, x] == 0:
        return None

    spans = _extract_connected_spans(working, x=x, y=y)
    left = min(span_left for _, span_left, _ in spans)
    right = max(span_right for _, _, span_right in spans)
    top = min(span_y for span_y, _, _ in spans)
    bottom = max(span_y for span_y, _, _ in spans)
    region_left = max(0, left - 1)
    region_right = min(width - 1, right + 1)
    region_top = max(0, top - 1)
    region_bottom = min(height - 1, bottom + 1)
    component = np.zeros(
        (region_bottom - region_top + 1, region_right - region_left + 1),
        dtype=np.uint8,
    )
    for span_y, span_left, span_right in spans:
        component[
            span_y - region_top,
            span_left - region_left : span_right - region_left + 1,
        ] = 255

    if grow:
        adjusted = _dilate_cross(component)
    else:
        adjusted = _erode_cross(
            component,
            touches_left=region_left == 0,
            touches_top=region_top == 0,
            touches_right=region_right == width - 1,
            touches_bottom=region_bottom == height - 1,
        )
    destination = working[
        region_top : region_bottom + 1,
        region_left : region_right + 1,
    ]
    np.maximum(destination, adjusted, out=destination)
    return working


def connected_component_extent(
    mask: np.ndarray,
    *,
    x: int,
    y: int,
) -> tuple[int, int, int, int] | None:
    """Return left, top, exclusive-right, and exclusive-bottom for a component."""
    working = np.array(_grayscale_array(mask), copy=True, order="C")
    height, width = working.shape
    if x < 0 or y < 0 or x >= width or y >= height or working[y, x] == 0:
        return None
    spans = _extract_connected_spans(working, x=x, y=y)
    return (
        min(span_left for _, span_left, _ in spans),
        min(span_y for span_y, _, _ in spans),
        max(span_right for _, _, span_right in spans) + 1,
        max(span_y for span_y, _, _ in spans) + 1,
    )


def outer_mask_border(mask: np.ndarray) -> np.ndarray:
    """Return the one-pixel outer border produced by a 3x3 square dilation."""
    source = _grayscale_array(mask)
    horizontal = np.array(source, copy=True, order="C")
    np.maximum(horizontal[:, 1:], source[:, :-1], out=horizontal[:, 1:])
    np.maximum(horizontal[:, :-1], source[:, 1:], out=horizontal[:, :-1])
    dilated = np.array(horizontal, copy=True, order="C")
    np.maximum(dilated[1:, :], horizontal[:-1, :], out=dilated[1:, :])
    np.maximum(dilated[:-1, :], horizontal[1:, :], out=dilated[:-1, :])
    return np.subtract(dilated, source, dtype=np.uint8)


def _extract_connected_spans(
    working: np.ndarray,
    *,
    x: int,
    y: int,
) -> list[tuple[int, int, int]]:
    """Erase one 8-connected component and return its horizontal spans."""
    height, width = working.shape
    pending = [(x, y)]
    spans: list[tuple[int, int, int]] = []
    while pending:
        seed_x, span_y = pending.pop()
        if working[span_y, seed_x] == 0:
            continue
        row = working[span_y]
        left_zeros = np.flatnonzero(row[:seed_x] == 0)
        span_left = int(left_zeros[-1] + 1) if left_zeros.size else 0
        right_zeros = np.flatnonzero(row[seed_x + 1 :] == 0)
        span_right = int(seed_x + right_zeros[0]) if right_zeros.size else width - 1
        working[span_y, span_left : span_right + 1] = 0
        spans.append((span_y, span_left, span_right))
        search_left = max(0, span_left - 1)
        search_right = min(width - 1, span_right + 1)
        for neighbor_y in (span_y - 1, span_y + 1):
            if neighbor_y < 0 or neighbor_y >= height:
                continue
            neighbor = working[neighbor_y]
            search = neighbor[search_left : search_right + 1] != 0
            if not np.any(search):
                continue
            run_starts = np.flatnonzero(search & np.concatenate(([True], ~search[:-1])))
            pending.extend(
                (search_left + int(run_start), neighbor_y) for run_start in run_starts
            )
    return spans


def _dilate_cross(component: np.ndarray) -> np.ndarray:
    """Dilate binary component pixels with a 3x3 cross kernel."""
    result = np.array(component, copy=True, order="C")
    np.maximum(result[1:, :], component[:-1, :], out=result[1:, :])
    np.maximum(result[:-1, :], component[1:, :], out=result[:-1, :])
    np.maximum(result[:, 1:], component[:, :-1], out=result[:, 1:])
    np.maximum(result[:, :-1], component[:, 1:], out=result[:, :-1])
    return result


def _erode_cross(
    component: np.ndarray,
    *,
    touches_left: bool,
    touches_top: bool,
    touches_right: bool,
    touches_bottom: bool,
) -> np.ndarray:
    """Erode binary component pixels while preserving image-edge foreground."""
    result = np.array(component, copy=True, order="C")
    result[1:, :] &= component[:-1, :]
    result[:-1, :] &= component[1:, :]
    result[:, 1:] &= component[:, :-1]
    result[:, :-1] &= component[:, 1:]
    if not touches_top:
        result[0, :] = 0
    if not touches_bottom:
        result[-1, :] = 0
    if not touches_left:
        result[:, 0] = 0
    if not touches_right:
        result[:, -1] = 0
    return result


def _grayscale_array(mask: np.ndarray) -> np.ndarray:
    """Validate and return a two-dimensional uint8 mask view."""
    array = np.asarray(mask)
    if array.ndim != 2:
        raise ValueError("mask arrays must be two-dimensional")
    if array.dtype != np.uint8:
        raise ValueError("mask arrays must use uint8 pixels")
    return array
