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

"""Version 14 shared-edge topology recovery contracts."""

from __future__ import annotations

import uuid

import numpy as np
from PySide6.QtCore import QPointF

from cutecanvas import LayerGeometryMode, RasterExtentPolicy
from cutecanvas.composition.layers import CompositionLayerInstance
from cutecanvas.coverage import CoverageAssetSnapshot, CoverageDocument
from cutecanvas.persistence.legacy_shared_edges import recover_legacy_layer_stack
from cutecanvas.raster.sparse_grid import SparseRasterGrid
from cutecanvas.resources import ProjectResourceReference
from cutecanvas.snapping.edge_model import polygon_edges
from qpane.sdk.scene import RasterBounds


def test_convergent_raster_edges_recover_one_exact_durable_seam() -> None:
    """A uniquely implied legacy wedge becomes exact manipulation topology."""
    bounds = RasterBounds(0, 0, 128, 128)
    first_pixels = np.zeros((128, 128), dtype=np.uint8)
    second_pixels = np.zeros((128, 128), dtype=np.uint8)
    for row in range(128):
        first_edge = round(48.0 + 0.5 * row)
        second_edge = round(50.0 + (62.0 / 127.0) * row)
        first_pixels[row, :first_edge] = 255
        second_pixels[row, second_edge:] = 255
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    layers = (
        CompositionLayerInstance(
            uuid.uuid4(),
            ProjectResourceReference(first_id),
        ),
        CompositionLayerInstance(
            uuid.uuid4(),
            ProjectResourceReference(second_id),
        ),
    )
    masks = {
        first_id: _asset(first_id, bounds, first_pixels),
        second_id: _asset(second_id, bounds, second_pixels),
    }

    recovered = recover_legacy_layer_stack(layers, masks)

    assert all(layer.geometry.mode is LayerGeometryMode.BOUNDARY for layer in recovered)
    first_edges = polygon_edges("first", recovered[0].geometry.boundary_points())
    second_edges = polygon_edges("second", recovered[1].geometry.boundary_points())
    assert any(
        _edge_coordinates(first.start, first.end)
        == _edge_coordinates(second.start, second.end)
        for first in first_edges
        for second in second_edges
    )


def _asset(
    asset_id: uuid.UUID,
    bounds: RasterBounds,
    pixels: np.ndarray,
) -> CoverageAssetSnapshot:
    """Return one raster-only mask archive value."""
    grid = SparseRasterGrid(channels=1, tile_size=128)
    grid.replace(bounds, pixels)
    return CoverageAssetSnapshot(
        grid.snapshot(bounds, RasterExtentPolicy.EXPAND_ON_WRITE),
        CoverageDocument(document_id=asset_id),
    )


def _edge_coordinates(
    first: QPointF,
    second: QPointF,
) -> tuple[tuple[float, float], ...]:
    """Return endpoint-order-independent coordinates for one edge."""
    return tuple(sorted(((first.x(), first.y()), (second.x(), second.y()))))
