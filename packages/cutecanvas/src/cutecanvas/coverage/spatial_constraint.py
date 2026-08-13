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

"""Own bounded spatial admission for coverage authorship and modification."""

from __future__ import annotations

import math
from typing import Protocol

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath

from qpane.sdk.raster import qimage_to_numpy_grayscale8
from qpane.sdk.scene import RasterBounds

from .surface import CoverageSnapshot


class CoverageSpatialConstraint(Protocol):
    """Provide bounded coverage admission without whole-canvas allocation."""

    @property
    def bounds(self) -> RasterBounds | None:
        """Return conservative source-space admission bounds."""
        ...

    def sample(self, bounds: RasterBounds, stride: int = 1) -> np.ndarray:
        """Return constraint coverage aligned to ``bounds``."""
        ...


class BoundsCoverageConstraint:
    """Expose one finite rectangular aperture as coverage samples."""

    def __init__(self, bounds: RasterBounds) -> None:
        """Retain one positive immutable aperture rectangle."""

        if bounds.width <= 0 or bounds.height <= 0:
            raise ValueError("coverage constraint bounds must be positive")
        self._bounds = bounds

    @property
    def bounds(self) -> RasterBounds:
        """Return the finite aperture bounds."""

        return self._bounds

    def sample(self, bounds: RasterBounds, stride: int = 1) -> np.ndarray:
        """Return full admission inside the aperture and zero outside it."""

        pixels = np.zeros((bounds.height, bounds.width), dtype=np.uint8)
        overlap = bounds.intersection(self._bounds)
        if overlap is not None:
            left = overlap.x - bounds.x
            top = overlap.y - bounds.y
            pixels[top : top + overlap.height, left : left + overlap.width] = 255
        sample_stride = max(1, int(stride))
        return pixels[::sample_stride, ::sample_stride]


class SnapshotCoverageConstraint:
    """Sample one immutable soft coverage constraint by requested region."""

    def __init__(self, coverage: CoverageSnapshot) -> None:
        """Retain one detached coverage snapshot."""

        self._coverage = coverage

    @property
    def bounds(self) -> RasterBounds | None:
        """Return constraint coverage bounds."""

        return self._coverage.bounds

    def sample(self, bounds: RasterBounds, stride: int = 1) -> np.ndarray:
        """Return constraint coverage aligned to one requested region."""

        pixels = _project_coverage(self._coverage, bounds)
        sample_stride = max(1, int(stride))
        return pixels[::sample_stride, ::sample_stride]


class PathCoverageConstraint:
    """Rasterize an exact canvas aperture only over requested regions."""

    def __init__(self, path: QPainterPath) -> None:
        """Detach one non-empty source-space aperture path."""

        detached = QPainterPath(path)
        self._path = detached
        self._bounds = _path_bounds(detached)

    @property
    def bounds(self) -> RasterBounds | None:
        """Return conservative path bounds."""

        return self._bounds

    def sample(self, bounds: RasterBounds, stride: int = 1) -> np.ndarray:
        """Rasterize the aperture over one region, then sample its stride."""

        image = QImage(bounds.width, bounds.height, QImage.Format_Grayscale8)
        image.fill(0)
        painter = QPainter(image)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255))
            painter.translate(-bounds.x, -bounds.y)
            painter.drawPath(self._path)
        finally:
            painter.end()
        pixels = qimage_to_numpy_grayscale8(image)
        sample_stride = max(1, int(stride))
        return pixels[::sample_stride, ::sample_stride]


def constrain_coverage_change(
    before: CoverageSnapshot,
    after: CoverageSnapshot | None,
    constraint: CoverageSpatialConstraint,
) -> CoverageSnapshot | None:
    """Adopt ``after`` inside the aperture while preserving outside source pixels."""

    before_bounds = before.bounds
    if before_bounds is None:
        raise ValueError("coverage constraint requires nonempty source coverage")
    after_bounds = None if after is None else after.bounds
    combined = (
        before_bounds if after_bounds is None else before_bounds.united(after_bounds)
    )
    before_pixels = _project_coverage(before, combined)
    after_pixels = _project_coverage(after, combined)
    aperture = constraint.sample(combined)
    coverage = aperture.astype(np.uint16)
    inverse = 255 - coverage
    blended = (
        before_pixels.astype(np.uint16) * inverse
        + after_pixels.astype(np.uint16) * coverage
        + 127
    ) // 255
    return _trim_coverage(
        CoverageSnapshot(
            combined,
            before.extent_policy,
            blended.astype(np.uint8),
        )
    )


def coverage_change_respects_constraint(
    before: CoverageSnapshot,
    after: CoverageSnapshot | None,
    constraint: CoverageSpatialConstraint,
) -> bool:
    """Return whether coverage remains unchanged outside the aperture."""

    before_bounds = before.bounds
    if before_bounds is None:
        return after is None or after.bounds is None
    after_bounds = None if after is None else after.bounds
    combined = (
        before_bounds if after_bounds is None else before_bounds.united(after_bounds)
    )
    before_pixels = _project_coverage(before, combined)
    after_pixels = _project_coverage(after, combined)
    outside = constraint.sample(combined) == 0
    return bool(np.array_equal(before_pixels[outside], after_pixels[outside]))


def _project_coverage(
    snapshot: CoverageSnapshot | None,
    bounds: RasterBounds,
) -> np.ndarray:
    """Project optional sparse coverage into explicit source-space bounds."""

    result = np.zeros((bounds.height, bounds.width), dtype=np.uint8)
    source = None if snapshot is None else snapshot.bounds
    if snapshot is None or source is None:
        return result
    overlap = source.intersection(bounds)
    if overlap is None:
        return result
    source_x = overlap.x - source.x
    source_y = overlap.y - source.y
    target_x = overlap.x - bounds.x
    target_y = overlap.y - bounds.y
    result[
        target_y : target_y + overlap.height,
        target_x : target_x + overlap.width,
    ] = snapshot.pixels[
        source_y : source_y + overlap.height,
        source_x : source_x + overlap.width,
    ]
    return result


def _trim_coverage(snapshot: CoverageSnapshot) -> CoverageSnapshot | None:
    """Remove zero-only margins while preserving source coordinates."""

    if snapshot.bounds is None or not np.any(snapshot.pixels):
        return None
    rows, columns = np.nonzero(snapshot.pixels)
    left = int(columns.min())
    top = int(rows.min())
    right = int(columns.max()) + 1
    bottom = int(rows.max()) + 1
    bounds = snapshot.bounds
    return CoverageSnapshot(
        RasterBounds(bounds.x + left, bounds.y + top, right - left, bottom - top),
        snapshot.extent_policy,
        np.ascontiguousarray(snapshot.pixels[top:bottom, left:right]),
    )


def _path_bounds(path: QPainterPath) -> RasterBounds | None:
    """Return conservative integer bounds for one finite painter path."""

    bounds = path.boundingRect()
    left = math.floor(bounds.left())
    top = math.floor(bounds.top())
    right = math.ceil(bounds.right())
    bottom = math.ceil(bounds.bottom())
    if right <= left or bottom <= top:
        return None
    return RasterBounds(left, top, right - left, bottom - top)


__all__ = [
    "BoundsCoverageConstraint",
    "CoverageSpatialConstraint",
    "PathCoverageConstraint",
    "SnapshotCoverageConstraint",
    "constrain_coverage_change",
    "coverage_change_respects_constraint",
]
