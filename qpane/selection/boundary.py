#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Efficient vector boundaries derived from pixel-selection coverage."""

from __future__ import annotations

import numpy as np
from PySide6.QtGui import QPainterPath

from ..coverage import CoverageSnapshot


class SelectionBoundaryBuilder:
    """Build cached run-length vector edges from thresholded coverage."""

    def build(
        self,
        coverage: CoverageSnapshot,
        *,
        threshold: int = 128,
    ) -> QPainterPath:
        """Return scene-coordinate boundary runs for ``coverage``."""
        bounds = coverage.bounds
        if bounds is None:
            return QPainterPath()
        selected = coverage.pixels >= np.uint8(threshold)
        path = QPainterPath()
        horizontal = np.zeros((selected.shape[0] + 1, selected.shape[1]), dtype=bool)
        horizontal[0, :] = selected[0, :]
        horizontal[-1, :] = selected[-1, :]
        horizontal[1:-1, :] = selected[:-1, :] != selected[1:, :]
        for y in np.flatnonzero(np.any(horizontal, axis=1)):
            row = horizontal[y]
            for start, end in _true_runs(row):
                path.moveTo(bounds.x + start, bounds.y + y)
                path.lineTo(bounds.x + end, bounds.y + y)

        vertical = np.zeros((selected.shape[0], selected.shape[1] + 1), dtype=bool)
        vertical[:, 0] = selected[:, 0]
        vertical[:, -1] = selected[:, -1]
        vertical[:, 1:-1] = selected[:, :-1] != selected[:, 1:]
        for x in np.flatnonzero(np.any(vertical, axis=0)):
            column = vertical[:, x]
            for start, end in _true_runs(column):
                path.moveTo(bounds.x + x, bounds.y + start)
                path.lineTo(bounds.x + x, bounds.y + end)
        return path


def _true_runs(values: np.ndarray) -> tuple[tuple[int, int], ...]:
    """Return half-open runs containing true values in one boolean vector."""
    padded = np.pad(values.astype(np.int8, copy=False), (1, 1))
    transitions = np.diff(padded)
    starts = np.flatnonzero(transitions == 1)
    ends = np.flatnonzero(transitions == -1)
    return tuple(zip(starts.tolist(), ends.tolist(), strict=True))
