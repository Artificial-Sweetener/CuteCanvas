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

"""Vectorized source-to-scene coordinates for piecewise brush tips."""

from __future__ import annotations

import numpy as np

from qpane.sdk.scene import PiecewiseLayerTransform


def map_piecewise_source_grid(
    mapping: PiecewiseLayerTransform,
    source_x: np.ndarray,
    source_y: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Map a rectangular source grid through deterministic affine patches."""
    if source_x.ndim != 1 or source_y.ndim != 1:
        raise ValueError("piecewise source grid axes must be one-dimensional")
    y_grid, x_grid = np.meshgrid(source_y, source_x, indexing="ij")
    scene_x = np.zeros_like(x_grid, dtype=np.float64)
    scene_y = np.zeros_like(y_grid, dtype=np.float64)
    valid = np.zeros_like(x_grid, dtype=np.bool_)
    for patch in mapping.patches:
        first = patch.source[0]
        edge_a = patch.source[1] - first
        edge_b = patch.source[2] - first
        determinant = edge_a.x() * edge_b.y() - edge_a.y() * edge_b.x()
        if abs(determinant) <= 1e-18:
            continue
        relative_x = x_grid - first.x()
        relative_y = y_grid - first.y()
        weight_a = (relative_x * edge_b.y() - relative_y * edge_b.x()) / determinant
        weight_b = (edge_a.x() * relative_y - edge_a.y() * relative_x) / determinant
        inside = (
            (weight_a >= -1e-9)
            & (weight_b >= -1e-9)
            & (weight_a + weight_b <= 1.0 + 1e-9)
            & ~valid
        )
        if not np.any(inside):
            continue
        transform = patch.transform
        scene_x[inside] = (
            transform.m11 * x_grid[inside]
            + transform.m21 * y_grid[inside]
            + transform.dx
        )
        scene_y[inside] = (
            transform.m12 * x_grid[inside]
            + transform.m22 * y_grid[inside]
            + transform.dy
        )
        valid[inside] = True
    return scene_x, scene_y, valid


__all__ = ["map_piecewise_source_grid"]
