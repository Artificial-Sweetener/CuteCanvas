#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Stable lower-bound performance guards for selected-pixel translation."""

from __future__ import annotations

import time
import uuid
from statistics import median

import numpy as np
from PySide6.QtGui import QColor, QImage

from qpane.coverage import CoverageSnapshot, CoverageSurface
from qpane.masks.mask import MaskLayer
from qpane.masks.pixel_translation import MaskPixelTranslator
from qpane.raster.color_surface import ColorRasterSurface
from qpane.raster.pixel_translation import ColorPixelTranslator
from qpane.scene.raster import RasterBounds, RasterExtentPolicy

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
    color_surface = ColorRasterSurface(image)
    color_translator = ColorPixelTranslator()
    mask = MaskLayer(
        uuid.uuid4(),
        CoverageSurface(np.full((1000, 1200), 255, dtype=np.uint8)),
    )
    mask_translator = MaskPixelTranslator()
    color_ms: list[float] = []
    mask_ms: list[float] = []

    for _sample in range(3):
        started = time.perf_counter()
        color_transition = color_translator.move(color_surface, selection, 200, 0)
        color_ms.append((time.perf_counter() - started) * 1000.0)
        assert color_transition is not None
        assert not color_transition.before_pixels.flags.writeable
        assert not color_transition.after_pixels.flags.writeable
        assert color_translator.restore(
            color_surface,
            color_transition,
            use_after=False,
        )

        started = time.perf_counter()
        mask_transition = mask_translator.move(mask, selection, 200, 0)
        mask_ms.append((time.perf_counter() - started) * 1000.0)
        assert mask_transition is not None
        assert not mask_transition.before_pixels.flags.writeable
        assert not mask_transition.after_pixels.flags.writeable
        assert mask_translator.restore(mask, mask_transition, use_after=False)

    assert median(color_ms) < _RGBA_MEDIAN_BUDGET_MS
    assert median(mask_ms) < _MASK_MEDIAN_BUDGET_MS
