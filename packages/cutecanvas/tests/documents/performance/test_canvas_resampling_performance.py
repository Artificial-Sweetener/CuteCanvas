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
"""Stable worker-performance contracts for whole-canvas resampling."""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage

from cutecanvas import CanvasDocument, CanvasResamplingMode
from cutecanvas_test_support.harness.timing import (
    INTERACTIVE_PERFORMANCE,
    average_interaction_latency_ms,
)

pytestmark = INTERACTIVE_PERFORMANCE

_FAST_ONE_MEGAPIXEL_BUDGET_MS = 100.0


def test_fast_one_megapixel_resampling_stays_within_worker_budget() -> None:
    """Keep the Qt-backed detached raster path below its latency contract."""
    image = QImage(512, 512, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(30, 120, 210, 255))
    document = CanvasDocument()
    composition_id = document.create_composition_from_image(image)
    plan = document._canvas_resampling_owner.capture(
        composition_id,
        QSize(1024, 1024),
        mode=CanvasResamplingMode.FAST,
    )
    products = []

    def build_product() -> None:
        """Retain each detached result so cleanup is outside the measurement."""
        products.append(document._canvas_resampling_owner.build(plan))

    elapsed_ms = average_interaction_latency_ms(build_product, repetitions=8)

    assert len(products) == 8
    assert elapsed_ms < _FAST_ONE_MEGAPIXEL_BUDGET_MS
    document.close()
