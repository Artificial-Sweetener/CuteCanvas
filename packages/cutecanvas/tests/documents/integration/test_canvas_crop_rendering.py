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
"""Rendering contracts for exact canvas crop geometry."""

from __future__ import annotations

from cutecanvas.document.canvas_crop import CanvasCropEffect, CanvasCropRenderOwner
from PySide6.QtCore import QPointF
from qpane.sdk.scene import RasterBounds


def test_canvas_crop_renderer_returns_the_exact_effect_polygon() -> None:
    """Clip inside the retained polygon without using target-bound shortcuts."""
    effect = CanvasCropEffect(
        (
            QPointF(2.0, 3.0),
            QPointF(8.0, 3.0),
            QPointF(8.0, 7.0),
            QPointF(2.0, 7.0),
        )
    )

    path = CanvasCropRenderOwner().clip_path(
        effect,
        RasterBounds(-100, -100, 200, 200),
    )

    assert path.contains(QPointF(5.0, 5.0))
    assert not path.contains(QPointF(1.0, 5.0))
    assert not path.contains(QPointF(9.0, 5.0))
