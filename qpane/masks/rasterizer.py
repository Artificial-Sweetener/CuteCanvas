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

"""Convert canonical grayscale masks into presentation-colored images."""

from __future__ import annotations

import numpy as np
from PySide6.QtGui import QColor, QImage

from ..raster.image_conversion import (
    numpy_to_qimage_argb32,
    qimage_to_numpy_grayscale8,
)
from .image_ops import outer_mask_border


class MaskRasterizer:
    """Build premultiplied ARGB overlays from grayscale mask pixels."""

    def __init__(self) -> None:
        """Precompute the alpha multiplication table shared by all renders."""
        alpha_values = np.arange(256, dtype=np.uint16)[:, None]
        color_values = np.arange(256, dtype=np.uint16)[None, :]
        self._premultiplied_alpha = ((alpha_values * color_values) // 255).astype(
            np.uint8
        )

    def rasterize(
        self,
        mask_image: QImage,
        color: QColor,
        *,
        draw_border: bool,
    ) -> QImage:
        """Return a detached premultiplied image for one mask presentation."""
        mask_pixels = qimage_to_numpy_grayscale8(mask_image)
        height, width = mask_pixels.shape
        output = np.zeros((height, width, 4), dtype=np.uint8)
        output[..., 0] = self._premultiplied_alpha[mask_pixels, color.blue()]
        output[..., 1] = self._premultiplied_alpha[mask_pixels, color.green()]
        output[..., 2] = self._premultiplied_alpha[mask_pixels, color.red()]
        output[..., 3] = mask_pixels
        if draw_border:
            border_alpha = outer_mask_border(mask_pixels)
            border_color = color.darker(120)
            border = np.zeros_like(output)
            border[..., 0] = self._premultiplied_alpha[
                border_alpha, border_color.blue()
            ]
            border[..., 1] = self._premultiplied_alpha[
                border_alpha, border_color.green()
            ]
            border[..., 2] = self._premultiplied_alpha[border_alpha, border_color.red()]
            border[..., 3] = border_alpha
            np.add(output, border, out=output, casting="unsafe")
        return numpy_to_qimage_argb32(output)
