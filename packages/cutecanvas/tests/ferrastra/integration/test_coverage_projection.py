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

"""Integration proof for CuteCanvas affine Coverage8 graph adaptation."""

from __future__ import annotations

import numpy as np
from cutecanvas.ferrastra import NativeCoverageProjector
from PySide6.QtCore import QSize
from qpane.sdk.scene import LayerTransform, RasterBounds


def test_identity_projection_preserves_detached_coverage_samples() -> None:
    """Coverage storage origin remains independent from authored coordinates."""
    source = np.array([[0, 64], [128, 255]], dtype=np.uint8)
    bounds = RasterBounds(10, -4, 2, 2)

    projected = NativeCoverageProjector().project(
        source,
        source_bounds=bounds,
        transform=LayerTransform(),
        destination_bounds=bounds,
    )

    np.testing.assert_array_equal(projected, source)
    assert not np.shares_memory(projected, source)


def test_fractional_projection_is_range_preserving_with_transparent_edges() -> None:
    """Linear coverage sampling remains scalar and bounded at fractional phase."""
    source = np.array([[0, 255]], dtype=np.uint8)

    projected = NativeCoverageProjector().project(
        source,
        source_bounds=RasterBounds(0, 0, 2, 1),
        transform=LayerTransform(dx=0.5),
        destination_bounds=RasterBounds(0, 0, 3, 1),
    )

    np.testing.assert_array_equal(projected, np.array([[0, 128, 128]], dtype=np.uint8))


def test_nearest_projection_selects_source_samples_without_interpolation() -> None:
    """Nearest mask policy remains a canonical native coverage mode."""
    source = np.array([[0, 255]], dtype=np.uint8)

    projected = NativeCoverageProjector().project(
        source,
        source_bounds=RasterBounds(0, 0, 2, 1),
        transform=LayerTransform(dx=0.5),
        destination_bounds=RasterBounds(0, 0, 3, 1),
        linear=False,
    )

    np.testing.assert_array_equal(projected, np.array([[0, 255, 0]], dtype=np.uint8))


def test_scale_uses_range_preserving_area_minification() -> None:
    """Whole-coverage reduction averages source area without photographic ringing."""
    source = np.array([[0, 128, 255, 255]], dtype=np.uint8)

    projected = NativeCoverageProjector().scale(source, QSize(2, 1))

    np.testing.assert_array_equal(projected, np.array([[64, 255]], dtype=np.uint8))
