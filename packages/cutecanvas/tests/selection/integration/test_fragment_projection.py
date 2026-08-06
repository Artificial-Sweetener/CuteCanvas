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
"""Contribution invariants for affine floating-fragment projection."""

from __future__ import annotations

import numpy as np
from cutecanvas.coverage import CoverageSnapshot
from cutecanvas.editor.fragment_projection import RasterFragmentProjector
from cutecanvas.scene.pixel_fragments import RasterPixelFormat, RasterPixelFragment
from cutecanvas.types import RasterExtentPolicy
from qpane.scene.affine import LayerTransform
from qpane.scene.raster import RasterBounds


def test_affine_projection_discards_coverage_when_payload_rounds_to_zero() -> None:
    """Resampling cannot leave destination authority behind transparent payload."""
    bounds = RasterBounds(0, 0, 2, 2)
    fragment = RasterPixelFragment(
        bounds,
        RasterPixelFormat.COVERAGE8,
        np.array([[1, 0], [0, 0]], dtype=np.uint8),
        CoverageSnapshot(
            bounds,
            RasterExtentPolicy.FIXED,
            np.array([[255, 0], [0, 0]], dtype=np.uint8),
        ),
    )

    projected = RasterFragmentProjector().project(
        fragment,
        source_transform=LayerTransform(),
        fragment_transform=LayerTransform(m11=0.5, m22=0.5),
        destination_transform=LayerTransform(),
    )

    assert projected is None
