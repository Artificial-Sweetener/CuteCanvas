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
"""Premultiplied clone compositing through the shared procedural brush tips."""

from __future__ import annotations

import numpy as np
from qpane.sdk.scene import RasterBounds

from .compositor import BrushCompositor
from .model import BrushDab


class CloneStampCompositor:
    """Composite revision-stable source pixels through resolved brush dabs."""

    def __init__(self, brushes: BrushCompositor) -> None:
        """Reuse the shared brush tip cache and projection policy."""
        self._tips = brushes.tip_projector

    def render_dabs(
        self,
        *,
        before: np.ndarray,
        source_pixels: np.ndarray,
        patch_bounds: RasterBounds,
        dabs: tuple[BrushDab, ...],
    ) -> np.ndarray:
        """Clone one aligned source patch through shared procedural brush tips."""
        if source_pixels.shape != before.shape or source_pixels.dtype != np.uint8:
            raise ValueError("clone source pixels must match destination pixels")
        result = np.array(before, copy=True, order="C")
        qt_bounds = patch_bounds.to_qrect()
        for dab in dabs:
            projected = self._tips.project(dab, qt_bounds, opacity=dab.opacity)
            if projected is None:
                continue
            target = (projected.rows, projected.columns)
            result[target] = _source_over(
                result[target],
                source_pixels[target],
                projected.alpha,
            )
        return result


def _source_over(
    destination: np.ndarray,
    source: np.ndarray,
    brush_alpha: np.ndarray,
) -> np.ndarray:
    """Composite premultiplied BGRA source through one brush-opacity plane."""
    source_wide = source.astype(np.uint32)
    destination_wide = destination.astype(np.uint32)
    coverage = brush_alpha.astype(np.uint32)
    source_alpha = (source_wide[:, :, 3] * coverage + 127) // 255
    scaled_source = (source_wide * coverage[:, :, None] + 127) // 255
    inverse = 255 - source_alpha
    output = scaled_source + (destination_wide * inverse[:, :, None] + 127) // 255
    return np.minimum(output, 255).astype(np.uint8)
