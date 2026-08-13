#    QPane - High-performance PySide6 image viewer
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

"""Numerical admission contracts for finite bounded layer mappings."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF

from qpane.scene.mapping import validate_layer_mapping
from qpane.sdk.scene import PiecewiseLayerTransform, RasterBounds


def test_bounded_mapping_accepts_inverse_round_trip_residue() -> None:
    """Subpixel numerical residue around exact raster edges remains admissible."""
    mapping = _mapping_with_left(79.99999999999999)

    validate_layer_mapping(mapping, RasterBounds(80, 80, 80, 100))


def test_bounded_mapping_rejects_meaningful_source_overflow() -> None:
    """Tolerance must not admit a boundary outside finite raster storage."""
    mapping = _mapping_with_left(79.999999)

    with pytest.raises(ValueError, match="bounded source boundary"):
        validate_layer_mapping(mapping, RasterBounds(80, 80, 80, 100))


def _mapping_with_left(left: float) -> PiecewiseLayerTransform:
    """Return a rectangular finite mapping with one controlled source edge."""
    source = (
        QPointF(left, 80.0),
        QPointF(160.0, 80.0),
        QPointF(160.0, 180.0),
        QPointF(left, 180.0),
    )
    return PiecewiseLayerTransform(source, source)
