#    QPane + CuteCanvas - High-performance PySide6 rendering and editing
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

"""Verify renderer-neutral overlay geometry exposed by CuteCanvas."""

from __future__ import annotations

import pytest
from cutecanvas import CanvasOverlayState
from PySide6.QtCore import QPointF, QRect, QRectF
from PySide6.QtGui import QImage, QTransform


@pytest.mark.parametrize(
    ("logical_size", "physical_size", "expected"),
    (
        ((800, 600), (800.0, 600.0), (2.0, 0.5)),
        ((800, 600), (1200.0, 900.0), (3.0, 0.75)),
        ((0, 0), (0.0, 0.0), (2.0, 0.5)),
    ),
)
def test_overlay_display_scale_uses_render_transform_and_physical_viewport(
    logical_size: tuple[int, int],
    physical_size: tuple[float, float],
    expected: tuple[float, float],
) -> None:
    """Report truthful physical source scale across DPR and empty-view edges."""

    transform = QTransform()
    transform.scale(2.0, 0.5)
    state = CanvasOverlayState(
        zoom=7.0,
        viewport=QRect(0, 0, *logical_size),
        source_image=QImage(20, 10, QImage.Format.Format_ARGB32_Premultiplied),
        transform=transform,
        pan=QPointF(),
        physical_viewport=QRectF(0.0, 0.0, *physical_size),
    )

    assert state.display_scale.horizontal == pytest.approx(expected[0])
    assert state.display_scale.vertical == pytest.approx(expected[1])
