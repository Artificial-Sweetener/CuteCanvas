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
"""Shared grayscale coverage storage for masks and pixel selections."""

from .asset import CoverageAsset, CoverageAssetSnapshot
from .authoring import CoverageShapeConfiguration, CoverageShapeOptions
from .document import (
    CoverageDocument,
    CoverageItem,
    RasterCoverageItem,
    StrokeCoverageItem,
    VectorCoverageItem,
)
from .evaluation import CoverageDocumentEvaluator
from .geometry import CoverageGeometryFactory
from .movement import CoverageItemMoveSession
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
    "CoverageAsset",
    "CoverageAssetSnapshot",
    "CoverageCombineMode",
    "CoverageDocument",
    "CoverageDocumentEvaluator",
    "CoverageGeometryFactory",
    "CoverageItem",
    "CoverageItemMoveSession",
    "CoverageShapeConfiguration",
    "CoverageShapeOptions",
    "CoverageSnapshot",
    "CoverageStateSnapshot",
    "CoverageSurface",
    "RasterCoverageItem",
    "StrokeCoverageItem",
    "VectorCoverageItem",
    "WritableCoverageRegion",
    "combine_coverage",
    "normalize_coverage_array",
    "reframe_coverage_snapshot",
]
