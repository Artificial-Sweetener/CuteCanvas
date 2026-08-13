#    QPane + CuteCanvas + Ferrastra - Native graphics architecture tooling
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

"""Prove exact QImage conversion and pyramid products at QPane's adapter boundary."""

from __future__ import annotations

import pytest
from ferrastra import RasterReconstructionSpace
from PySide6.QtGui import QColor, QImage
from qpane.execution.cancellation import CancellationToken
from qpane.ferrastra import (
    generate_exact_pyramid_levels,
    qimage_from_rgba8,
    qimage_to_rgba8,
)


def test_qimage_round_trip_preserves_premultiplied_channel_meaning() -> None:
    """Translate byte order without changing visible color or alpha."""
    source = QImage(2, 1, QImage.Format_ARGB32_Premultiplied)
    source.setPixelColor(0, 0, QColor(10, 20, 30, 128))
    source.setPixelColor(1, 0, QColor(200, 100, 50, 255))

    rgba = qimage_to_rgba8(source)
    restored = qimage_from_rgba8(
        rgba.pixels,
        rgba.width,
        rgba.height,
        rgba.stride_bytes,
    )

    assert restored.format() == QImage.Format_ARGB32_Premultiplied
    assert restored.pixelColor(0, 0) == source.pixelColor(0, 0)
    assert restored.pixelColor(1, 0) == source.pixelColor(1, 0)


def test_exact_pyramid_levels_keep_dimensions_pixels_and_detached_storage() -> None:
    """Produce reusable half-scale QImages with canonical native pixels."""
    source = QImage(8, 4, QImage.Format_ARGB32_Premultiplied)
    source.fill(QColor(65, 105, 225, 255))

    product = generate_exact_pyramid_levels(source, 1, CancellationToken())

    assert tuple(product.levels) == (0.5, 0.25)
    assert [level.size().toTuple() for level in product.levels.values()] == [
        (4, 2),
        (2, 1),
    ]
    assert all(
        level.pixelColor(0, 0) == QColor(65, 105, 225, 255)
        for level in product.levels.values()
    )
    assert product.size_bytes == sum(
        level.sizeInBytes() for level in product.levels.values()
    )


def test_cancelled_pyramid_request_publishes_no_levels() -> None:
    """Reject before retaining a source or publishing a partial level set."""
    source = QImage(8, 8, QImage.Format_ARGB32_Premultiplied)
    source.fill(QColor("black"))
    cancellation = CancellationToken()
    cancellation._cancel("superseded")

    with pytest.raises(RuntimeError, match="superseded"):
        generate_exact_pyramid_levels(source, 1, cancellation)


def test_pyramid_reconstruction_defaults_encoded_and_supports_linear_light() -> None:
    """Encoded and linear reconstruction must remain distinct selectable products."""
    source = QImage(2, 2, QImage.Format_ARGB32_Premultiplied)
    source.setPixelColor(0, 0, QColor("black"))
    source.setPixelColor(1, 0, QColor("white"))
    source.setPixelColor(0, 1, QColor("white"))
    source.setPixelColor(1, 1, QColor("black"))

    encoded = generate_exact_pyramid_levels(source, 1, CancellationToken())
    linear = generate_exact_pyramid_levels(
        source,
        1,
        CancellationToken(),
        reconstruction_space=RasterReconstructionSpace.SRGB_LINEAR,
    )

    encoded_gray = encoded.levels[0.5].pixelColor(0, 0).red()
    linear_gray = linear.levels[0.5].pixelColor(0, 0).red()
    assert 120 <= encoded_gray <= 136
    assert 180 <= linear_gray <= 196
