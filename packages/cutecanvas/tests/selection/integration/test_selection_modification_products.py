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
"""Pure pixel-selection modification geometry and soft-coverage contracts."""

from __future__ import annotations

import numpy as np
import pytest

from cutecanvas.coverage import CoverageSnapshot
from cutecanvas.selection import (
    PixelSelectionModificationRequest,
    build_pixel_selection_modification,
)
from cutecanvas.types import (
    LayerEdgeOperation,
    RasterExtentPolicy,
)
from qpane.sdk.scene import RasterBounds


def test_expand_grows_selection_without_changing_soft_values() -> None:
    """Expansion must translate the complete grayscale edge into padded bounds."""
    source = _snapshot(
        RasterBounds(10, 20, 3, 3),
        np.array(
            [
                [0, 40, 0],
                [80, 200, 120],
                [0, 160, 0],
            ],
            dtype=np.uint8,
        ),
    )

    result = build_pixel_selection_modification(
        PixelSelectionModificationRequest(
            source,
            RasterBounds(0, 0, 100, 100),
            LayerEdgeOperation.EXPAND,
            2,
        )
    )

    assert result is not None
    assert result.bounds == RasterBounds(8, 18, 7, 7)
    assert result.pixels[0, 3] == 40
    assert result.pixels[3, 3] == 200
    assert result.pixels[6, 3] == 160


def test_contract_can_clear_selection_and_remains_a_valid_product() -> None:
    """Contraction larger than a selected island must produce no selection."""
    source = _snapshot(
        RasterBounds(5, 5, 3, 3),
        np.full((3, 3), 255, dtype=np.uint8),
    )

    result = build_pixel_selection_modification(
        PixelSelectionModificationRequest(
            source,
            RasterBounds(0, 0, 20, 20),
            LayerEdgeOperation.CONTRACT,
            2,
        )
    )

    assert result is None


def test_expand_and_feather_clip_to_finite_canvas() -> None:
    """Outward operations must never publish coverage beyond the canvas aperture."""
    canvas = RasterBounds(0, 0, 8, 8)
    source = _snapshot(
        RasterBounds(0, 0, 3, 3),
        np.full((3, 3), 255, dtype=np.uint8),
    )

    expanded = build_pixel_selection_modification(
        PixelSelectionModificationRequest(
            source,
            canvas,
            LayerEdgeOperation.EXPAND,
            4,
        )
    )
    feathered = build_pixel_selection_modification(
        PixelSelectionModificationRequest(
            source,
            canvas,
            LayerEdgeOperation.FEATHER,
            2.5,
        )
    )

    assert expanded is not None and expanded.bounds == RasterBounds(0, 0, 7, 7)
    assert feathered is not None and feathered.bounds is not None
    assert canvas.contains(feathered.bounds)
    assert np.any((feathered.pixels > 0) & (feathered.pixels < 255))


def test_contract_treats_canvas_and_storage_exterior_as_unselected() -> None:
    """A full-canvas selection must inset from every finite canvas edge."""
    source = _snapshot(
        RasterBounds(0, 0, 9, 9),
        np.full((9, 9), 255, dtype=np.uint8),
    )

    result = build_pixel_selection_modification(
        PixelSelectionModificationRequest(
            source,
            RasterBounds(0, 0, 9, 9),
            LayerEdgeOperation.CONTRACT,
            2,
        )
    )

    assert result is not None
    assert result.bounds == RasterBounds(2, 2, 5, 5)
    assert np.all(result.pixels == 255)


@pytest.mark.parametrize(
    ("operation", "radius"),
    (
        (LayerEdgeOperation.EXPAND, 1.5),
        (LayerEdgeOperation.CONTRACT, 2.25),
        (LayerEdgeOperation.FEATHER, float("inf")),
        (LayerEdgeOperation.FEATHER, -1.0),
    ),
)
def test_request_rejects_invalid_operation_radii(
    operation: LayerEdgeOperation,
    radius: float,
) -> None:
    """Request validation must reject ambiguous or unsafe pixel radii."""
    with pytest.raises(ValueError):
        PixelSelectionModificationRequest(
            _snapshot(RasterBounds(0, 0, 1, 1), np.full((1, 1), 255, np.uint8)),
            RasterBounds(0, 0, 10, 10),
            operation,
            radius,
        )


def _snapshot(bounds: RasterBounds, pixels: np.ndarray) -> CoverageSnapshot:
    """Build one immutable expanding coverage snapshot for a test."""
    return CoverageSnapshot(
        bounds,
        RasterExtentPolicy.EXPAND_ON_WRITE,
        pixels,
    )
