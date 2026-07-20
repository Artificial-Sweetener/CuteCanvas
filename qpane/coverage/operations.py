#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Centralized algebra for combining grayscale coverage fields."""

from __future__ import annotations

from enum import Enum

import numpy as np

from .surface import normalize_coverage_array


class CoverageCombineMode(str, Enum):
    """Operations supported when committing incoming coverage."""

    REPLACE = "replace"
    ADD = "add"
    SUBTRACT = "subtract"
    INTERSECT = "intersect"


def combine_coverage(
    existing: np.ndarray,
    incoming: np.ndarray,
    mode: CoverageCombineMode,
) -> np.ndarray:
    """Return coverage combined with normalized alpha compositing math."""
    destination = _coverage_operand(existing)
    source = _coverage_operand(incoming)
    if destination.shape != source.shape:
        raise ValueError("coverage arrays must have matching shapes")
    operation = CoverageCombineMode(mode)
    if operation is CoverageCombineMode.REPLACE:
        return np.array(source, copy=True, order="C")
    if operation is CoverageCombineMode.INTERSECT and destination.size:
        if int(destination.min()) == 255:
            return np.array(source, copy=True, order="C")
        if int(source.min()) == 255:
            return np.array(destination, copy=True, order="C")
    destination_wide = destination.astype(np.uint16)
    source_wide = source.astype(np.uint16)
    if operation is CoverageCombineMode.ADD:
        combined = source_wide + _multiply_coverage(
            destination_wide,
            255 - source_wide,
        )
    elif operation is CoverageCombineMode.SUBTRACT:
        combined = _multiply_coverage(destination_wide, 255 - source_wide)
    else:
        combined = _multiply_coverage(destination_wide, source_wide)
    return np.ascontiguousarray(combined.astype(np.uint8))


def _multiply_coverage(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """Multiply uint16 coverage with nearest-integer normalization."""
    return (left * right + 127) // 255


def _coverage_operand(array: np.ndarray) -> np.ndarray:
    """Return normalized read-only input without copying canonical uint8 arrays."""
    candidate = np.asarray(array)
    if candidate.dtype == np.uint8 and candidate.ndim == 2:
        return candidate
    return normalize_coverage_array(candidate)
