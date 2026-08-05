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
"""Bounded grayscale coverage filters shared by authoring operations."""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np

_LINE_CHUNK = 64


class CoverageFilterCancelledError(RuntimeError):
    """Report cooperative cancellation between bounded filter bands."""


def dilate_coverage(
    pixels: np.ndarray,
    radius: int,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> np.ndarray:
    """Expand grayscale coverage by a square pixel radius."""
    return _extreme_filter(pixels, radius, maximum=True, cancelled=cancelled)


def erode_coverage(
    pixels: np.ndarray,
    radius: int,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> np.ndarray:
    """Contract grayscale coverage by a square pixel radius."""
    return _extreme_filter(pixels, radius, maximum=False, cancelled=cancelled)


def feather_coverage(
    pixels: np.ndarray,
    radius: float,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> np.ndarray:
    """Approximate Gaussian feathering with cancellable bounded box passes."""
    source = _coverage_array(pixels)
    normalized_radius = float(radius)
    if not math.isfinite(normalized_radius) or normalized_radius < 0.0:
        raise ValueError("coverage feather radius must be finite and non-negative")
    if normalized_radius == 0.0 or source.size == 0:
        return np.array(source, copy=True, order="C")
    box_radius = max(1, round(normalized_radius * 0.57735))
    result = source.astype(np.float32)
    for _ in range(3):
        _box_blur_axis_in_place(
            result,
            box_radius,
            axis=1,
            cancelled=cancelled,
        )
        _box_blur_axis_in_place(
            result,
            box_radius,
            axis=0,
            cancelled=cancelled,
        )
    _raise_if_cancelled(cancelled)
    return np.ascontiguousarray(np.clip(np.rint(result), 0, 255).astype(np.uint8))


def _extreme_filter(
    pixels: np.ndarray,
    radius: int,
    *,
    maximum: bool,
    cancelled: Callable[[], bool] | None,
) -> np.ndarray:
    """Apply a separable flat grayscale morphology filter in linear time."""
    source = _coverage_array(pixels)
    normalized_radius = int(radius)
    if normalized_radius != radius or normalized_radius < 0:
        raise ValueError("coverage morphology radius must be a non-negative integer")
    if normalized_radius == 0 or source.size == 0:
        return np.array(source, copy=True, order="C")
    horizontal = _extreme_axis(
        source,
        normalized_radius,
        axis=1,
        maximum=maximum,
        cancelled=cancelled,
    )
    return _extreme_axis(
        horizontal,
        normalized_radius,
        axis=0,
        maximum=maximum,
        cancelled=cancelled,
    )


def _extreme_axis(
    pixels: np.ndarray,
    radius: int,
    *,
    axis: int,
    maximum: bool,
    cancelled: Callable[[], bool] | None,
) -> np.ndarray:
    """Filter independent lines with bounded van Herk prefix/suffix products."""
    lines = pixels if axis == 1 else pixels.T
    output = np.empty_like(lines)
    window = radius * 2 + 1
    operator = np.maximum if maximum else np.minimum
    for start in range(0, lines.shape[0], _LINE_CHUNK):
        _raise_if_cancelled(cancelled)
        stop = min(lines.shape[0], start + _LINE_CHUNK)
        chunk = np.pad(lines[start:stop], ((0, 0), (radius, radius)))
        remainder = (-chunk.shape[1]) % window
        if remainder:
            chunk = np.pad(chunk, ((0, 0), (0, remainder)))
        blocks = chunk.reshape(chunk.shape[0], -1, window)
        prefix = operator.accumulate(blocks, axis=2).reshape(chunk.shape)
        suffix = operator.accumulate(blocks[:, :, ::-1], axis=2)[:, :, ::-1].reshape(
            chunk.shape
        )
        output[start:stop] = operator(
            suffix[:, : lines.shape[1]],
            prefix[:, window - 1 : window - 1 + lines.shape[1]],
        )
    _raise_if_cancelled(cancelled)
    result = output if axis == 1 else output.T
    return np.ascontiguousarray(result)


def _box_blur_axis_in_place(
    pixels: np.ndarray,
    radius: int,
    *,
    axis: int,
    cancelled: Callable[[], bool] | None,
) -> None:
    """Blur independent lines without retaining another full float image."""
    lines = pixels if axis == 1 else pixels.T
    width = radius * 2 + 1
    for start in range(0, lines.shape[0], _LINE_CHUNK):
        _raise_if_cancelled(cancelled)
        stop = min(lines.shape[0], start + _LINE_CHUNK)
        padded = np.pad(
            lines[start:stop],
            ((0, 0), (radius, radius)),
            mode="constant",
        )
        cumulative = np.cumsum(padded, axis=1, dtype=np.float32)
        cumulative = np.concatenate(
            (
                np.zeros((cumulative.shape[0], 1), dtype=np.float32),
                cumulative,
            ),
            axis=1,
        )
        lines[start:stop] = (cumulative[:, width:] - cumulative[:, :-width]) / width
    _raise_if_cancelled(cancelled)


def _coverage_array(pixels: np.ndarray) -> np.ndarray:
    """Require the canonical two-dimensional uint8 coverage representation."""
    source = np.asarray(pixels)
    if source.ndim != 2 or source.dtype != np.uint8:
        raise ValueError("coverage filters require a two-dimensional uint8 array")
    return source


def _raise_if_cancelled(cancelled: Callable[[], bool] | None) -> None:
    """Stop between bounded products when the caller revoked the request."""
    if cancelled is not None and cancelled():
        raise CoverageFilterCancelledError("coverage filtering cancelled")


__all__ = [
    "CoverageFilterCancelledError",
    "dilate_coverage",
    "erode_coverage",
    "feather_coverage",
]
