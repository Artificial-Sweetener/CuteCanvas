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

"""Persistence contracts for explicit manipulation polygons."""

from __future__ import annotations

import pytest

from cutecanvas.composition.geometry_policy import (
    LayerGeometryMode,
    LayerGeometryPolicy,
)
from cutecanvas.persistence.layer_geometry_codec import (
    decode_layer_geometry,
    encode_layer_geometry,
)


def test_boundary_geometry_round_trips_exact_vertex_coordinates() -> None:
    """Archives must retain the exact edited topology after raster baking."""
    policy = LayerGeometryPolicy(
        LayerGeometryMode.BOUNDARY,
        custom_boundary=((10.25, 20.5), (80.0, 24.75), (62.5, 91.0)),
    )

    restored = decode_layer_geometry(encode_layer_geometry(policy))

    assert restored == policy


def test_boundary_geometry_rejects_incomplete_manifest_points() -> None:
    """Malformed archive polygons must fail at the persistence boundary."""
    with pytest.raises(ValueError, match="two values"):
        decode_layer_geometry(
            {
                "mode": "boundary",
                "custom_bounds": None,
                "custom_boundary": [[0.0, 0.0], [10.0], [0.0, 10.0]],
            }
        )
