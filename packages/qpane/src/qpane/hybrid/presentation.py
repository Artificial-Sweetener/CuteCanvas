#    QPane - High-performance PySide6 image viewer
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
"""Present sampled hybrid coverage as premultiplied color pixels."""

from __future__ import annotations

from functools import lru_cache

import numpy as np
from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QColor, QImage

from ..raster.image_conversion import (
    qimage_to_numpy_view_argb32,
    qimage_to_numpy_view_grayscale8,
)
from .evaluation import HybridDocumentEvaluator
from .model import HybridDocument, HybridPresentationStyle


def present_hybrid_coverage(
    image: QImage,
    style: HybridPresentationStyle,
) -> QImage:
    """Return premultiplied color pixels for grayscale coverage."""
    coverage, backing = qimage_to_numpy_view_grayscale8(image)
    presented = present_hybrid_pixels(coverage, style)
    del backing
    return presented


def present_hybrid_pixels(
    coverage: np.ndarray,
    style: HybridPresentationStyle,
) -> QImage:
    """Return premultiplied color pixels from contiguous grayscale coverage."""
    normalized = np.asarray(coverage, dtype=np.uint8)
    if normalized.ndim != 2:
        raise ValueError("hybrid coverage must be a two-dimensional uint8 array")
    backing = _colorized_coverage(normalized, style.color)
    if style.outline_color is not None:
        border = _outer_border(normalized)
        outline = _colorized_coverage(border, style.outline_color)
        output, backing = qimage_to_numpy_view_argb32(backing)
        outline_pixels, outline = qimage_to_numpy_view_argb32(outline)
        np.maximum(output, outline_pixels, out=output)
    return backing


def present_hybrid_sample(
    document: HybridDocument,
    style: HybridPresentationStyle,
    source_rect: QRectF,
    pixel_size: QSize,
) -> QImage:
    """Evaluate and present one exact zero-origin hybrid source sample."""
    if source_rect.isEmpty() or pixel_size.isEmpty():
        return QImage()
    document_rect = QRectF(source_rect).translated(
        float(document.bounds.x),
        float(document.bounds.y),
    )
    coverage = HybridDocumentEvaluator().evaluate_pixels(
        document,
        document_rect,
        pixel_size,
    )
    return present_hybrid_pixels(coverage, style)


def _colorized_coverage(coverage: np.ndarray, color: QColor) -> QImage:
    """Colorize coverage without contending on Qt's cross-thread painter state."""
    height, width = coverage.shape
    target = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    pixels, backing = qimage_to_numpy_view_argb32(target)
    np.take(
        _premultiplied_color_table(*color.getRgb()),
        coverage,
        axis=0,
        out=pixels,
    )
    return backing


@lru_cache(maxsize=64)
def _premultiplied_color_table(
    red: int,
    green: int,
    blue: int,
    alpha: int,
) -> np.ndarray:
    """Return exact Qt-compatible BGRA values for every coverage byte."""
    coverage = np.arange(256, dtype=np.uint16)
    table = np.empty((256, 4), dtype=np.uint8)
    components = (blue, green, red)
    for channel, component in enumerate(components):
        premultiplied = _divide_by_255(component * alpha)
        table[:, channel] = _divide_by_255(coverage * premultiplied)
    table[:, 3] = _divide_by_255(coverage * alpha)
    table.flags.writeable = False
    return table


def _divide_by_255(values: np.ndarray | int) -> np.ndarray:
    """Apply Qt's nearest-integer eight-bit multiplication normalization."""
    wide = np.asarray(values, dtype=np.uint16)
    return (wide + (wide >> 8) + 128) >> 8


def _outer_border(coverage: np.ndarray) -> np.ndarray:
    """Return one-pixel outer coverage without crossing tile bleed."""
    padded = np.pad(coverage, 1, mode="constant")
    expanded = np.zeros_like(coverage)
    for y in range(3):
        for x in range(3):
            np.maximum(
                expanded,
                padded[y : y + coverage.shape[0], x : x + coverage.shape[1]],
                out=expanded,
            )
    np.subtract(expanded, coverage, out=expanded)
    return expanded
