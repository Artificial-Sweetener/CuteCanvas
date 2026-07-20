#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""NumPy compositor for cached procedural brush tips on raster targets."""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor

from .model import BrushDab, BrushOperation
from .tip_cache import BrushTipCache


class BrushCompositor:
    """Own cached tip products and target-format compositing algorithms."""

    def __init__(self, tips: BrushTipCache | None = None) -> None:
        """Bind a cache or create one bounded private cache."""
        self.tips = BrushTipCache() if tips is None else tips

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
            alpha = self._positioned_alpha(
                scaled,
                patch_bounds,
                opacity=scaled.opacity,
            )
            if alpha is None:
                continue
            target, source_alpha = alpha
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
            positioned = self._positioned_alpha(
                dab,
                patch_bounds,
                opacity=dab.opacity * color_alpha,
            )
            if positioned is None:
                continue
            target, alpha = positioned
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

    def _positioned_alpha(
        self,
        dab: BrushDab,
        patch_bounds: QRect,
        *,
        opacity: float,
    ) -> tuple[tuple[slice, slice], np.ndarray] | None:
        """Clip one cached tip to its destination and apply dab opacity."""
        tip = self.tips.tip(
            diameter=dab.diameter,
            hardness=dab.hardness,
            texture_strength=dab.texture_strength,
            texture_scale=dab.texture_scale,
            texture_seed=dab.texture_seed,
            angle=dab.angle,
        )
        left = math.floor(dab.center[0] - (tip.shape[1] - 1) / 2.0)
        top = math.floor(dab.center[1] - (tip.shape[0] - 1) / 2.0)
        right = left + tip.shape[1]
        bottom = top + tip.shape[0]
        clip_left = max(left, patch_bounds.left())
        clip_top = max(top, patch_bounds.top())
        clip_right = min(right, patch_bounds.left() + patch_bounds.width())
        clip_bottom = min(bottom, patch_bounds.top() + patch_bounds.height())
        if clip_left >= clip_right or clip_top >= clip_bottom:
            return None
        source = tip[
            clip_top - top : clip_bottom - top,
            clip_left - left : clip_right - left,
        ]
        alpha = np.rint(
            source.astype(np.float32) * min(1.0, max(0.0, float(opacity)))
        ).astype(np.uint8)
        target = (
            slice(clip_top - patch_bounds.top(), clip_bottom - patch_bounds.top()),
            slice(clip_left - patch_bounds.left(), clip_right - patch_bounds.left()),
        )
        return target, alpha


def _scaled_dab(dab: BrushDab, stride: int) -> BrushDab:
    """Return one dab projected into a stride-reduced preview patch."""
    if stride == 1:
        return dab
    return BrushDab(
        center=(dab.center[0] / stride, dab.center[1] / stride),
        diameter=max(1.0, dab.diameter / stride),
        hardness=dab.hardness,
        opacity=dab.opacity,
        angle=dab.angle,
        texture_strength=dab.texture_strength,
        texture_scale=max(0.25, dab.texture_scale / stride),
        texture_seed=dab.texture_seed,
    )
