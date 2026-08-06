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

"""Verify bounded transient support reservations for empty hybrid layers."""

from __future__ import annotations

import uuid

from qpane.rendering.transient_hybrid_support import TransientHybridSupport
from qpane.scene.raster import RasterBounds


def test_horizontal_support_growth_does_not_inflate_vertical_reservation() -> None:
    """Repeated x-axis growth must retain one stable y-axis block envelope."""

    scene_id = uuid.uuid4()
    layer_id = uuid.uuid4()
    support = TransientHybridSupport()
    heights: list[int] = []

    for x in range(0, 2048, 64):
        resolved = support.resolve(
            (scene_id, layer_id, RasterBounds(x, 1024, 32, 32)),
            scene_id,
        )[layer_id]
        heights.append(resolved.height)

    assert heights == [128] * len(heights)
