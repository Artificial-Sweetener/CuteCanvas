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

"""Vectorized coordinates for complete joined-edge layer mappings."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF

from qpane.sdk.scene import BilinearLayerTransform


def map_bilinear_source_grid(
    mapping: BilinearLayerTransform,
    source_x: np.ndarray,
    source_y: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Map a rectangular source-coordinate grid into scene coordinates."""
    if source_x.ndim != 1 or source_y.ndim != 1:
        raise ValueError("bilinear source grid axes must be one-dimensional")
    scene_x = np.zeros((source_y.size, source_x.size), dtype=np.float64)
    scene_y = np.zeros_like(scene_x)
    valid = np.zeros_like(scene_x, dtype=np.bool_)
    for row, local_y in enumerate(source_y):
        u, v, row_valid = inverse_bilinear_source_row(
            mapping.source_boundary,
            source_x,
            float(local_y),
        )
        mapped_x, mapped_y = bilinear_coordinates(
            mapping.target_boundary,
            u,
            v,
        )
        scene_x[row] = mapped_x
        scene_y[row] = mapped_y
        valid[row] = row_valid
    return scene_x, scene_y, valid


def bilinear_coordinates(
    boundary: tuple[QPointF, QPointF, QPointF, QPointF],
    u: np.ndarray,
    v: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Evaluate detached boundary coordinates for normalized values."""
    top_x = boundary[0].x() * (1.0 - u) + boundary[1].x() * u
    top_y = boundary[0].y() * (1.0 - u) + boundary[1].y() * u
    bottom_x = boundary[3].x() * (1.0 - u) + boundary[2].x() * u
    bottom_y = boundary[3].y() * (1.0 - u) + boundary[2].y() * u
    return (
        top_x * (1.0 - v) + bottom_x * v,
        top_y * (1.0 - v) + bottom_y * v,
    )


def inverse_bilinear_source_row(
    source: tuple[QPointF, QPointF, QPointF, QPointF],
    x: np.ndarray,
    y: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Solve normalized bilinear source coordinates for one raster row."""
    horizontal = source[1] - source[0]
    vertical = source[3] - source[0]
    determinant = horizontal.x() * vertical.y() - horizontal.y() * vertical.x()
    relative_x = x - source[0].x()
    relative_y = y - source[0].y()
    if abs(determinant) <= 1e-18:
        u = np.full_like(x, 0.5)
        v = np.full_like(x, 0.5)
    else:
        u = (relative_x * vertical.y() - relative_y * vertical.x()) / determinant
        v = (horizontal.x() * relative_y - horizontal.y() * relative_x) / determinant
    for _iteration in range(8):
        current_x, current_y = bilinear_coordinates(source, u, v)
        error_x = current_x - x
        error_y = current_y - y
        derivative_u_x = (source[1].x() - source[0].x()) * (1.0 - v) + (
            source[2].x() - source[3].x()
        ) * v
        derivative_u_y = (source[1].y() - source[0].y()) * (1.0 - v) + (
            source[2].y() - source[3].y()
        ) * v
        derivative_v_x = (source[3].x() - source[0].x()) * (1.0 - u) + (
            source[2].x() - source[1].x()
        ) * u
        derivative_v_y = (source[3].y() - source[0].y()) * (1.0 - u) + (
            source[2].y() - source[1].y()
        ) * u
        jacobian = derivative_u_x * derivative_v_y - derivative_u_y * derivative_v_x
        solvable = np.abs(jacobian) > 1e-18
        delta_u = np.zeros_like(u)
        delta_v = np.zeros_like(v)
        np.divide(
            error_x * derivative_v_y - error_y * derivative_v_x,
            jacobian,
            out=delta_u,
            where=solvable,
        )
        np.divide(
            derivative_u_x * error_y - derivative_u_y * error_x,
            jacobian,
            out=delta_v,
            where=solvable,
        )
        u -= delta_u
        v -= delta_v
    current_x, current_y = bilinear_coordinates(source, u, v)
    residual = np.hypot(current_x - x, current_y - y)
    valid = (
        (residual <= 1e-6)
        & (u >= -1e-9)
        & (u <= 1.0 + 1e-9)
        & (v >= -1e-9)
        & (v <= 1.0 + 1e-9)
    )
    return np.clip(u, 0.0, 1.0), np.clip(v, 0.0, 1.0), valid


__all__ = [
    "bilinear_coordinates",
    "inverse_bilinear_source_row",
    "map_bilinear_source_grid",
]
