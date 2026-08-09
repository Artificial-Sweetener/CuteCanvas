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
"""NumPy compositor for cached procedural brush tips on raster targets."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor
from qpane.sdk.scene import LayerTransform

from .model import BrushDab, BrushOperation
from .tip_cache import BrushTipCache
from .tip_projection import BrushTipProjector


class BrushCompositor:
    """Own cached tip products and target-format compositing algorithms."""

    def __init__(self, tips: BrushTipCache | None = None) -> None:
        """Bind a cache or create one bounded private cache."""
        self.tips = BrushTipCache() if tips is None else tips
        self.tip_projector = BrushTipProjector(self.tips)

    def render_coverage_dabs(
        self,
        *,
        before: np.ndarray,
        patch_bounds: QRect,
        dabs: tuple[BrushDab, ...],
        operation: BrushOperation,
        stride: int = 1,
    ) -> np.ndarray:
        """Composite textured dabs into one grayscale coverage patch."""
        result = np.array(before, copy=True, order="C")
        if result.dtype != np.uint8 or result.ndim != 2:
            raise ValueError("coverage compositor requires a uint8 2D patch")
        for dab in dabs:
            scaled = _scaled_dab(dab, max(1, int(stride)))
            projected = self.tip_projector.project(
                scaled,
                patch_bounds,
                opacity=scaled.opacity,
            )
            if projected is None:
                continue
            target = (projected.rows, projected.columns)
            source_alpha = projected.alpha
            destination = result[target]
            inverse = 255 - source_alpha.astype(np.uint16)
            if operation is BrushOperation.ERASE:
                result[target] = (destination.astype(np.uint16) * inverse + 127) // 255
            else:
                result[target] = (
                    source_alpha
                    + (destination.astype(np.uint16) * inverse + 127) // 255
                )
        return result

    def render_color_dabs(
        self,
        *,
        before: np.ndarray,
        patch_bounds: QRect,
        dabs: tuple[BrushDab, ...],
        operation: BrushOperation,
        color: QColor,
    ) -> np.ndarray:
        """Composite textured dabs into one premultiplied BGRA patch."""
        result = np.array(before, copy=True, order="C")
        if result.dtype != np.uint8 or result.ndim != 3 or result.shape[2] != 4:
            raise ValueError("color compositor requires a uint8 BGRA patch")
        color_alpha = color.alpha() / 255.0
        channels = np.array(
            [color.blue(), color.green(), color.red()],
            dtype=np.uint16,
        )
        for dab in dabs:
            projected = self.tip_projector.project(
                dab,
                patch_bounds,
                opacity=dab.opacity * color_alpha,
            )
            if projected is None:
                continue
            target = (projected.rows, projected.columns)
            alpha = projected.alpha
            destination = result[target].astype(np.uint16)
            inverse = 255 - alpha.astype(np.uint16)
            if operation is BrushOperation.ERASE:
                result[target] = (destination * inverse[:, :, None] + 127) // 255
                continue
            source_rgb = (
                channels[None, None, :] * alpha[:, :, None].astype(np.uint16) + 127
            ) // 255
            output = np.empty_like(destination)
            output[:, :, :3] = (
                source_rgb + (destination[:, :, :3] * inverse[:, :, None] + 127) // 255
            )
            output[:, :, 3] = alpha + (destination[:, :, 3] * inverse + 127) // 255
            result[target] = np.minimum(output, 255).astype(np.uint8)
        return result


def _scaled_dab(dab: BrushDab, stride: int) -> BrushDab:
    """Return one dab projected into a stride-reduced preview patch."""
    if stride == 1:
        return dab
    mapping = dab.tip_mapping
    return BrushDab(
        center=(dab.center[0] / stride, dab.center[1] / stride),
        diameter=(
            dab.diameter if mapping is not None else max(1.0, dab.diameter / stride)
        ),
        hardness=dab.hardness,
        opacity=dab.opacity,
        angle=dab.angle,
        texture_strength=dab.texture_strength,
        texture_scale=(
            dab.texture_scale
            if mapping is not None
            else max(0.25, dab.texture_scale / stride)
        ),
        texture_seed=dab.texture_seed,
        tip_transform=dab.tip_transform,
        tip_mapping=(
            None
            if mapping is None
            else mapping.preceded_by(LayerTransform(m11=stride, m22=stride))
        ),
    )
