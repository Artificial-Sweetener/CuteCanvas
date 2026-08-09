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
from PySide6.QtCore import QPointF, QRect
from qpane.sdk.scene import (
    BilinearLayerTransform,
    LayerTransform,
    PiecewiseLayerTransform,
    RasterBounds,
)

from cutecanvas.coverage.bilinear_coordinates import map_bilinear_source_grid

from .model import BrushDab
from .piecewise_tip_coordinates import map_piecewise_source_grid
from .tip_cache import BrushTipCache
from .tip_geometry import brush_dab_bounds

_IDENTITY_TRANSFORM = LayerTransform()


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
        if dab.tip_mapping is not None:
            return _project_bounded_tip(dab, patch_bounds, tip)
        if dab.tip_transform != _IDENTITY_TRANSFORM:
            return _project_affine_tip(dab, patch_bounds, tip)
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


def _project_bounded_tip(
    dab: BrushDab,
    patch_bounds: QRect,
    tip: np.ndarray,
) -> ProjectedBrushTip | None:
    """Sample one scene-space tip through its exact bounded mapping."""
    mapping = dab.tip_mapping
    if mapping is None:
        raise ValueError("bounded tip projection requires a mapping")
    destination = brush_dab_bounds(dab).intersection(
        RasterBounds.from_qrect(patch_bounds)
    )
    if destination is None:
        return None
    local_x = np.arange(destination.x, destination.right, dtype=np.float64) + 0.5
    local_y = np.arange(destination.y, destination.bottom, dtype=np.float64) + 0.5
    if isinstance(mapping, BilinearLayerTransform):
        scene_x, scene_y, valid = map_bilinear_source_grid(
            mapping,
            local_x,
            local_y,
        )
    elif isinstance(mapping, PiecewiseLayerTransform):
        scene_x, scene_y, valid = map_piecewise_source_grid(
            mapping,
            local_x,
            local_y,
        )
    else:
        raise TypeError("bounded tip mapping is unsupported")
    scene_center = mapping.map_point(QPointF(*dab.center))
    source_x = scene_x - scene_center.x() + (tip.shape[1] - 1) / 2.0
    source_y = scene_y - scene_center.y() + (tip.shape[0] - 1) / 2.0
    alpha = _bilinear_sample(tip, source_x, source_y)
    alpha[~valid] = 0
    return ProjectedBrushTip(
        rows=slice(
            destination.y - patch_bounds.top(),
            destination.bottom - patch_bounds.top(),
        ),
        columns=slice(
            destination.x - patch_bounds.left(),
            destination.right - patch_bounds.left(),
        ),
        alpha=alpha,
    )


def _project_affine_tip(
    dab: BrushDab,
    patch_bounds: QRect,
    tip: np.ndarray,
) -> ProjectedBrushTip | None:
    """Inverse-sample one canonical tip into its target-local affine footprint."""

    destination = brush_dab_bounds(dab).intersection(
        RasterBounds.from_qrect(patch_bounds)
    )
    inverse = dab.tip_transform.inverted()
    if destination is None or inverse is None:
        return None
    x = np.arange(destination.x, destination.right, dtype=np.float32)
    y = np.arange(destination.y, destination.bottom, dtype=np.float32)
    y_grid, x_grid = np.meshgrid(y, x, indexing="ij")
    local_x = x_grid - float(dab.center[0])
    local_y = y_grid - float(dab.center[1])
    canonical_x = inverse.m11 * local_x + inverse.m21 * local_y
    canonical_y = inverse.m12 * local_x + inverse.m22 * local_y
    source_x = canonical_x + (tip.shape[1] - 1) / 2.0
    source_y = canonical_y + (tip.shape[0] - 1) / 2.0
    alpha = _bilinear_sample(tip, source_x, source_y)
    return ProjectedBrushTip(
        rows=slice(
            destination.y - patch_bounds.top(),
            destination.bottom - patch_bounds.top(),
        ),
        columns=slice(
            destination.x - patch_bounds.left(),
            destination.right - patch_bounds.left(),
        ),
        alpha=alpha,
    )


def _bilinear_sample(
    source: np.ndarray,
    source_x: np.ndarray,
    source_y: np.ndarray,
) -> np.ndarray:
    """Return zero-bordered bilinear uint8 samples at floating coordinates."""

    padded = np.pad(source, 1, mode="constant")
    x = source_x + 1.0
    y = source_y + 1.0
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    x1 = x0 + 1
    y1 = y0 + 1
    x0 = np.clip(x0, 0, padded.shape[1] - 1)
    x1 = np.clip(x1, 0, padded.shape[1] - 1)
    y0 = np.clip(y0, 0, padded.shape[0] - 1)
    y1 = np.clip(y1, 0, padded.shape[0] - 1)
    weight_x = x - np.floor(x)
    weight_y = y - np.floor(y)
    top = padded[y0, x0] * (1.0 - weight_x) + padded[y0, x1] * weight_x
    bottom = padded[y1, x0] * (1.0 - weight_x) + padded[y1, x1] * weight_x
    return np.rint(top * (1.0 - weight_y) + bottom * weight_y).astype(np.uint8)
