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

"""Persistence contracts for durable layer mapping variants."""

from __future__ import annotations

import pytest
from cutecanvas.persistence.layer_mapping_codec import (
    decode_layer_mapping,
    encode_layer_mapping,
)
from PySide6.QtCore import QPointF
from qpane.sdk.scene import BilinearLayerTransform, PiecewiseLayerTransform


def test_piecewise_mapping_round_trips_boundary_topology() -> None:
    """Archive values retain every inserted source and target vertex."""
    mapping = PiecewiseLayerTransform(
        (
            QPointF(0.0, 0.0),
            QPointF(10.0, 0.0),
            QPointF(10.0, 5.0),
            QPointF(10.0, 10.0),
            QPointF(0.0, 10.0),
        ),
        (
            QPointF(0.0, 0.0),
            QPointF(12.0, 0.0),
            QPointF(10.0, 5.0),
            QPointF(10.0, 10.0),
            QPointF(0.0, 10.0),
        ),
    )

    restored = decode_layer_mapping(encode_layer_mapping(mapping))

    assert restored == mapping


def test_bilinear_mapping_round_trips_full_source_topology() -> None:
    """Archives retain full source coverage when one target edge is joined."""
    mapping = BilinearLayerTransform(
        (
            QPointF(0.0, 0.0),
            QPointF(10.0, 0.0),
            QPointF(10.0, 10.0),
            QPointF(0.0, 10.0),
        ),
        (
            QPointF(10.0, 0.0),
            QPointF(10.0, 0.0),
            QPointF(10.0, 10.0),
            QPointF(0.0, 10.0),
        ),
    )

    restored = decode_layer_mapping(encode_layer_mapping(mapping))

    assert isinstance(restored, BilinearLayerTransform)
    assert restored == mapping


def test_piecewise_mapping_rejects_oversized_or_ambiguous_manifest_objects() -> None:
    """Untrusted archives fail before allocating or accepting hidden fields."""
    point = [0.0, 0.0]
    with pytest.raises(ValueError, match="4 to 128"):
        decode_layer_mapping(
            {
                "kind": "piecewise",
                "source": [point] * 129,
                "target": [point] * 129,
            }
        )
    with pytest.raises(ValueError, match="unsupported"):
        decode_layer_mapping(
            {
                "kind": "piecewise",
                "source": [point] * 4,
                "target": [point] * 4,
                "future": True,
            }
        )
