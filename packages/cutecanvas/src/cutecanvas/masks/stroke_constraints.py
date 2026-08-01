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

"""Lazy region sampling for mask-stroke authoring constraints."""

from __future__ import annotations

import math
from typing import Protocol

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath
from qpane.sdk.raster import qimage_to_numpy_grayscale8
from qpane.sdk.scene import RasterBounds

from ..coverage import CoverageSnapshot


class MaskStrokeConstraint(Protocol):
    """Provide bounded mask-stroke admission without whole-canvas allocation."""

    @property
    def bounds(self) -> RasterBounds | None:
        """Return conservative layer-local admission bounds."""
        ...

    def sample(self, bounds: RasterBounds, stride: int = 1) -> np.ndarray:
        """Return constraint coverage aligned to ``bounds``."""
        ...


class CoverageStrokeConstraint:
    """Sample an immutable soft pixel-selection constraint by dirty region."""

    def __init__(self, coverage: CoverageSnapshot) -> None:
        """Retain one detached selection snapshot."""
        self._coverage = coverage

    @property
    def bounds(self) -> RasterBounds | None:
        """Return selection coverage bounds."""
        return self._coverage.bounds

    def sample(self, bounds: RasterBounds, stride: int = 1) -> np.ndarray:
        """Return selection coverage aligned to one requested region."""
        pixels = np.zeros((bounds.height, bounds.width), dtype=np.uint8)
        coverage_bounds = self._coverage.bounds
        if coverage_bounds is not None:
            overlap = bounds.intersection(coverage_bounds)
            if overlap is not None:
                source_x = overlap.x - coverage_bounds.x
                source_y = overlap.y - coverage_bounds.y
                target_x = overlap.x - bounds.x
                target_y = overlap.y - bounds.y
                pixels[
                    target_y : target_y + overlap.height,
                    target_x : target_x + overlap.width,
                ] = self._coverage.pixels[
                    source_y : source_y + overlap.height,
                    source_x : source_x + overlap.width,
                ]
        sample_stride = max(1, int(stride))
        return pixels[::sample_stride, ::sample_stride]


class PathStrokeConstraint:
    """Rasterize an affine canvas aperture only over requested dirty regions."""

    def __init__(self, path: QPainterPath) -> None:
        """Detach a non-empty layer-local aperture path."""
        detached = QPainterPath(path)
        self._path = detached
        self._bounds = _path_bounds(detached)

    @property
    def bounds(self) -> RasterBounds | None:
        """Return conservative path bounds."""
        return self._bounds

    def sample(self, bounds: RasterBounds, stride: int = 1) -> np.ndarray:
        """Rasterize the aperture over one dirty region, then sample its stride."""
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
