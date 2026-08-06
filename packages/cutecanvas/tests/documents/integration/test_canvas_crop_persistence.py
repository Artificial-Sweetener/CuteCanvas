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
"""Persistence contracts for explicit canvas crop effects."""

from __future__ import annotations

import pytest
from cutecanvas.document.canvas_crop import CanvasCropEffect
from cutecanvas.persistence.effect_codec import (
    decode_layer_effect,
    encode_layer_effect,
)
from PySide6.QtCore import QPointF


def test_canvas_crop_effect_round_trips_exact_target_local_geometry() -> None:
    """Preserve crop identity and polygon coordinates without a resource shim."""
    effect = CanvasCropEffect(
        (
            QPointF(-2.5, 1.25),
            QPointF(10.0, 1.25),
            QPointF(9.5, 8.0),
            QPointF(-2.0, 7.75),
        )
    )

    restored = decode_layer_effect(encode_layer_effect(effect))

    assert restored == effect
    assert restored.kind == "canvas-crop"
    assert restored.retained_sources == ()


@pytest.mark.parametrize(
    "payload",
    (
        {"kind": "canvas-crop", "points": []},
        {"kind": "canvas-crop", "points": [[0.0, 0.0], [1.0], [1.0, 1.0]]},
        {"kind": "canvas-crop", "points": [[0.0, 0.0], [1.0, 0.0], [1e400, 1.0]]},
    ),
)
def test_canvas_crop_effect_rejects_malformed_archive_geometry(payload) -> None:
    """Reject underspecified, malformed, and non-finite crop polygons."""
    with pytest.raises((TypeError, ValueError)):
        decode_layer_effect(payload)
