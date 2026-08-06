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
"""Stable lower-bound performance guards for selected-pixel translation."""

from __future__ import annotations

import uuid

import numpy as np
from cutecanvas.coverage import CoverageAsset, CoverageSnapshot, CoverageSurface
from cutecanvas.masks.mask import MaskLayer
from cutecanvas.masks.pixel_translation import MaskPixelTranslator
from cutecanvas.raster.color_surface import ColorRasterSurface
from cutecanvas.raster.pixel_translation import ColorPixelTranslator
from cutecanvas.types import RasterExtentPolicy
from cutecanvas_test_support.harness.timing import (
    INTERACTIVE_PERFORMANCE,
    average_interaction_latency_ms,
)
from PySide6.QtGui import QColor, QImage
from qpane.scene.raster import RasterBounds

pytestmark = INTERACTIVE_PERFORMANCE

_RGBA_MEDIAN_BUDGET_MS = 50.0
_MASK_MEDIAN_BUDGET_MS = 15.0


def _large_hard_selection() -> CoverageSnapshot:
    """Return representative one-megapixel binary movement coverage."""
    return CoverageSnapshot(
        RasterBounds(0, 0, 1000, 1000),
        RasterExtentPolicy.FIXED,
        np.full((1000, 1000), 255, dtype=np.uint8),
    )


def test_one_megapixel_hard_translation_stays_below_commit_budgets() -> None:
    """Common hard mask and RGBA commits must retain their vectorized fast paths."""
    selection = _large_hard_selection()
    image = QImage(1200, 1000, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(30, 120, 210, 255))
    repetitions = 16
    color_surfaces = tuple(ColorRasterSurface(image.copy()) for _ in range(repetitions))
    color_translator = ColorPixelTranslator()
    masks = tuple(
        MaskLayer(
            mask_id,
            CoverageAsset(
                mask_id,
                CoverageSurface(np.full((1000, 1200), 255, dtype=np.uint8)),
            ),
        )
        for mask_id in (uuid.uuid4() for _ in range(repetitions))
    )
    mask_translator = MaskPixelTranslator()
    color_sources = iter(color_surfaces)
    mask_sources = iter(masks)
    color_transitions = []
    mask_transitions = []

    def move_color() -> None:
        """Exercise one RGBA translation on an independent source."""
        color_surface = next(color_sources)
        color_transition = color_translator.move(color_surface, selection, 200, 0)
        assert color_transition is not None
        assert not color_transition.before_pixels.flags.writeable
        assert not color_transition.after_pixels.flags.writeable
        color_transitions.append((color_surface, color_transition))

    def move_mask() -> None:
        """Exercise one mask translation on an independent source."""
        mask = next(mask_sources)
        mask_transition = mask_translator.move(mask, selection, 200, 0)
        assert mask_transition is not None
        assert not mask_transition.before_pixels.flags.writeable
        assert not mask_transition.after_pixels.flags.writeable
        mask_transitions.append((mask, mask_transition))

    color_ms = average_interaction_latency_ms(
        move_color,
        repetitions=repetitions,
    )
    mask_ms = average_interaction_latency_ms(
        move_mask,
        repetitions=repetitions,
    )
    assert color_ms < _RGBA_MEDIAN_BUDGET_MS
    assert mask_ms < _MASK_MEDIAN_BUDGET_MS
    for color_surface, transition in color_transitions:
        assert color_translator.restore(color_surface, transition, use_after=False)
    for mask, transition in mask_transitions:
        assert mask_translator.restore(mask, transition, use_after=False)
