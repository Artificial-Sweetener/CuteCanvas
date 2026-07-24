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

import numpy as np
from PySide6.QtGui import QImage

from ..raster.image_conversion import (
    numpy_to_qimage_argb32,
    qimage_to_numpy_grayscale8,
)
from .model import HybridPresentationStyle


def present_hybrid_coverage(
    image: QImage,
    style: HybridPresentationStyle,
) -> QImage:
    """Return premultiplied color pixels for grayscale coverage."""
    coverage = qimage_to_numpy_grayscale8(image)
    alpha = coverage.astype(np.uint16)
    color = style.color
    output = np.empty((*coverage.shape, 4), dtype=np.uint8)
    output[..., 0] = ((alpha * color.blue()) // 255).astype(np.uint8)
    output[..., 1] = ((alpha * color.green()) // 255).astype(np.uint8)
    output[..., 2] = ((alpha * color.red()) // 255).astype(np.uint8)
    output[..., 3] = coverage
    if style.outline_color is not None:
        border = _outer_border(coverage)
        border_alpha = border.astype(np.uint16)
        outline = style.outline_color
        output[..., 0] = np.maximum(
            output[..., 0],
            ((border_alpha * outline.blue()) // 255).astype(np.uint8),
        )
        output[..., 1] = np.maximum(
            output[..., 1],
            ((border_alpha * outline.green()) // 255).astype(np.uint8),
        )
        output[..., 2] = np.maximum(
            output[..., 2],
            ((border_alpha * outline.red()) // 255).astype(np.uint8),
        )
        output[..., 3] = np.maximum(output[..., 3], border)
    return numpy_to_qimage_argb32(output)


def _outer_border(coverage: np.ndarray) -> np.ndarray:
    """Return one-pixel outer coverage without crossing tile bleed."""
    padded = np.pad(coverage, 1, mode="constant")
    expanded = np.zeros_like(coverage)
    for y in range(3):
        for x in range(3):
            expanded = np.maximum(
                expanded,
                padded[y : y + coverage.shape[0], x : x + coverage.shape[1]],
            )
    return np.maximum(expanded.astype(np.int16) - coverage, 0).astype(np.uint8)
