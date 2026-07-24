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
"""Clip cached procedural tips into bounded destination patches."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QRect

from .model import BrushDab
from .tip_cache import BrushTipCache


@dataclass(frozen=True, slots=True)
class ProjectedBrushTip:
    """Pair destination slices with the matching clipped opacity pixels."""

    rows: slice
    columns: slice
    alpha: np.ndarray

    def __post_init__(self) -> None:
        """Retain the cache-owned read-only opacity view without copying."""
        alpha = np.asarray(self.alpha)
        if alpha.dtype != np.uint8 or alpha.ndim != 2:
            raise ValueError("projected tip alpha must be a uint8 plane")
        object.__setattr__(self, "alpha", alpha)


class BrushTipProjector:
    """Own brush-tip cache lookup, positioning, and patch clipping."""

    def __init__(self, tips: BrushTipCache) -> None:
        """Bind the coordinated procedural tip cache."""
        self._tips = tips

    def project(
        self,
        dab: BrushDab,
        patch_bounds: QRect,
        *,
        opacity: float,
    ) -> ProjectedBrushTip | None:
        """Return one clipped opacity tip in destination patch coordinates."""
        tip = self._tips.opacity_tip(
            diameter=dab.diameter,
            hardness=dab.hardness,
            texture_strength=dab.texture_strength,
            texture_scale=dab.texture_scale,
            texture_seed=dab.texture_seed,
            angle=dab.angle,
            opacity=opacity,
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
        return ProjectedBrushTip(
            rows=slice(
                clip_top - patch_bounds.top(),
                clip_bottom - patch_bounds.top(),
            ),
            columns=slice(
                clip_left - patch_bounds.left(),
                clip_right - patch_bounds.left(),
            ),
            alpha=tip[
                clip_top - top : clip_bottom - top,
                clip_left - left : clip_right - left,
            ],
        )
