#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Shared grayscale coverage storage for masks and pixel selections."""

from .operations import CoverageCombineMode, combine_coverage
from .projection import AffineCoverageResampler
from .surface import (
    CoverageSnapshot,
    CoverageStateSnapshot,
    CoverageSurface,
    WritableCoverageRegion,
    normalize_coverage_array,
    reframe_coverage_snapshot,
)

__all__ = [
    "AffineCoverageResampler",
    "CoverageCombineMode",
    "CoverageSnapshot",
    "CoverageStateSnapshot",
    "CoverageSurface",
    "WritableCoverageRegion",
    "combine_coverage",
    "normalize_coverage_array",
    "reframe_coverage_snapshot",
]
