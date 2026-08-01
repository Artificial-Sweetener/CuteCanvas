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
"""Render lightweight DPR-aware controls from authoritative brush tips."""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage
from qpane.sdk.raster import numpy_to_qimage_argb32

from .model import BrushPreset
from .tip_cache import BrushTipCache


class BrushTipPreviewRenderer:
    """Project a brush preset into a compact transparent UI preview."""

    def __init__(self, tips: BrushTipCache) -> None:
        """Reuse the same byte-bounded tip cache as production painting."""
        self._tips = tips

    def render(
        self,
        preset: BrushPreset,
        logical_size: QSize,
        *,
        device_pixel_ratio: float = 1.0,
        color: QColor | None = None,
    ) -> QImage:
        """Return a centered premultiplied tip at the requested density."""
        if not isinstance(preset, BrushPreset):
            raise TypeError("preset must be a BrushPreset")
        if not isinstance(logical_size, QSize) or logical_size.isEmpty():
            raise ValueError("logical_size must be a positive QSize")
        ratio = float(device_pixel_ratio)
        if not math.isfinite(ratio) or ratio <= 0.0:
            raise ValueError("device_pixel_ratio must be finite and positive")
        resolved_color = QColor("white") if color is None else color
        if not isinstance(resolved_color, QColor) or not resolved_color.isValid():
            raise TypeError("color must be a valid QColor")
        width = max(1, math.ceil(logical_size.width() * ratio))
        height = max(1, math.ceil(logical_size.height() * ratio))
        diameter = max(1.0, min(width, height) - 4.0 * ratio)
        alpha = self._tips.opacity_tip(
            diameter=diameter,
            hardness=preset.hardness,
            texture_strength=preset.texture_strength,
            texture_scale=preset.texture_scale * ratio,
            texture_seed=preset.texture_seed,
            angle=preset.angle,
            opacity=preset.opacity,
        )
        pixels = np.zeros((height, width, 4), dtype=np.uint8)
        left = (width - alpha.shape[1]) // 2
        top = (height - alpha.shape[0]) // 2
        rows = slice(top, top + alpha.shape[0])
        columns = slice(left, left + alpha.shape[1])
        coverage = alpha.astype(np.uint16)
        pixels[rows, columns, 0] = (coverage * resolved_color.blue() + 127) // 255
        pixels[rows, columns, 1] = (coverage * resolved_color.green() + 127) // 255
        pixels[rows, columns, 2] = (coverage * resolved_color.red() + 127) // 255
        pixels[rows, columns, 3] = (coverage * resolved_color.alpha() + 127) // 255
        image = numpy_to_qimage_argb32(pixels)
        image.setDevicePixelRatio(ratio)
        return image


__all__ = ["BrushTipPreviewRenderer"]
