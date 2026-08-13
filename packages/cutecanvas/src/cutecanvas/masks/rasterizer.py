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

"""Convert canonical grayscale masks into presentation-colored images."""

from __future__ import annotations

from PySide6.QtGui import QColor, QImage
from qpane.sdk.raster import present_hybrid_pixels, qimage_to_numpy_grayscale8

from qpane import HybridPresentationStyle


class MaskRasterizer:
    """Build premultiplied ARGB overlays from grayscale mask pixels."""

    def rasterize(
        self,
        mask_image: QImage,
        color: QColor,
        *,
        draw_border: bool,
    ) -> QImage:
        """Return a detached premultiplied image for one mask presentation."""
        pixels = qimage_to_numpy_grayscale8(mask_image)
        outline = color.darker(120) if draw_border else None
        return present_hybrid_pixels(
            pixels,
            HybridPresentationStyle(color, outline),
        )
