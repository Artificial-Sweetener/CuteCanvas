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

"""Coverage spatial-constraint ownership and change-admission contracts."""

from __future__ import annotations

import numpy as np

from cutecanvas.coverage import CoverageSnapshot
from cutecanvas.coverage.spatial_constraint import (
    BoundsCoverageConstraint,
    SnapshotCoverageConstraint,
    constrain_coverage_change,
    coverage_change_respects_constraint,
)
from cutecanvas.types import RasterExtentPolicy
from qpane.sdk.scene import RasterBounds


def test_bounds_constraint_preserves_existing_exterior_and_rejects_new_escape() -> None:
    """A bounded edit may change its aperture without erasing hidden source content."""

    before = _snapshot(
        RasterBounds(-1, 0, 4, 2),
        np.array([[90, 0, 0, 0], [0, 0, 0, 70]], dtype=np.uint8),
    )
    escaped = _snapshot(
        RasterBounds(-1, 0, 4, 2),
        np.array([[255, 200, 0, 0], [0, 0, 180, 255]], dtype=np.uint8),
    )
    constraint = BoundsCoverageConstraint(RasterBounds(0, 0, 2, 2))

    constrained = constrain_coverage_change(before, escaped, constraint)

    assert constrained is not None
    assert constrained.bounds == before.bounds
    assert np.array_equal(
        constrained.pixels,
        np.array([[90, 200, 0, 0], [0, 0, 180, 70]], dtype=np.uint8),
    )
    assert not coverage_change_respects_constraint(before, escaped, constraint)
    assert coverage_change_respects_constraint(before, constrained, constraint)


def test_soft_constraint_blends_changes_at_partial_coverage() -> None:
    """Soft aperture values must proportionally admit a coverage change."""

    before = _snapshot(RasterBounds(4, 5, 1, 1), np.array([[40]], dtype=np.uint8))
    after = _snapshot(RasterBounds(4, 5, 1, 1), np.array([[240]], dtype=np.uint8))
    constraint = SnapshotCoverageConstraint(
        _snapshot(RasterBounds(4, 5, 1, 1), np.array([[128]], dtype=np.uint8))
    )

    constrained = constrain_coverage_change(before, after, constraint)

    assert constrained is not None
    assert constrained.pixels[0, 0] == 140


def _snapshot(bounds: RasterBounds, pixels: np.ndarray) -> CoverageSnapshot:
    """Return one expanding detached coverage snapshot."""

    return CoverageSnapshot(bounds, RasterExtentPolicy.EXPAND_ON_WRITE, pixels)
