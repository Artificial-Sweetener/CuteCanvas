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
"""Tests for antialiased vector-to-selection rasterization."""

from __future__ import annotations

import numpy as np
from cutecanvas.coverage import CoverageSnapshot
from cutecanvas.selection import SelectionBoundaryBuilder, SelectionGeometryRasterizer
from cutecanvas.types import RasterExtentPolicy
from PySide6.QtCore import QPointF, QRectF
from qpane.scene.raster import RasterBounds


def test_rectangle_preserves_fractional_scene_alignment() -> None:
    snapshot = SelectionGeometryRasterizer().rectangle(QRectF(3.25, 7.5, 4.5, 3.0))

    assert snapshot.bounds == RasterBounds(3, 7, 5, 4)
    assert snapshot.pixels.shape == (4, 5)
    assert np.any((snapshot.pixels > 0) & (snapshot.pixels < 255))
    assert snapshot.pixels.max() == 255


def test_ellipse_has_soft_edges_and_opaque_interior() -> None:
    snapshot = SelectionGeometryRasterizer().ellipse(QRectF(-2.5, 4.25, 12.0, 10.0))

    assert snapshot.bounds == RasterBounds(-3, 4, 13, 11)
    assert np.any((snapshot.pixels > 0) & (snapshot.pixels < 255))
    assert snapshot.pixels.max() == 255
    assert snapshot.pixels[5, 6] == 255


def test_lasso_closes_polygon_and_rejects_incomplete_geometry() -> None:
    rasterizer = SelectionGeometryRasterizer()
    snapshot = rasterizer.lasso(
        [
            QPointF(1.5, 1.5),
            QPointF(8.5, 2.5),
            QPointF(4.5, 9.5),
        ]
    )

    assert snapshot.bounds == RasterBounds(1, 1, 8, 9)
    assert snapshot.pixels[3, 3] > 0
    assert snapshot.pixels[8, 0] == 0

    try:
        rasterizer.lasso([QPointF(), QPointF(1.0, 1.0)])
    except ValueError as error:
        assert "three points" in str(error)
    else:
        raise AssertionError("incomplete lasso geometry must be rejected")


def test_boundary_builder_compresses_large_rectangles_into_edge_runs() -> None:
    coverage = CoverageSnapshot(
        bounds=RasterBounds(0, 0, 3840, 2160),
        extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
        pixels=np.full((2160, 3840), 255, dtype=np.uint8),
    )

    path = SelectionBoundaryBuilder().build(coverage)

    assert path.elementCount() == 8
    assert path.boundingRect() == QRectF(0.0, 0.0, 3840.0, 2160.0)
