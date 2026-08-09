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

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from .authoring import CoverageShapeConfiguration, CoverageShapeOptions
from .document import (
    CoverageDocument,
    CoverageItem,
    RasterCoverageItem,
    StrokeCoverageItem,
    VectorCoverageItem,
)
from .filters import (
    CoverageFilterCancelledError,
    dilate_coverage,
    erode_coverage,
    feather_coverage,
)
from .geometry import CoverageGeometryFactory
from .modification import (
    CoverageEdgeModificationRequest,
    build_coverage_edge_modification,
)
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

if TYPE_CHECKING:
    from .asset import CoverageAsset, CoverageAssetSnapshot
    from .evaluation import CoverageDocumentEvaluator
    from .movement import CoverageItemMoveSession

_DEFERRED_EXPORTS = {
    "CoverageAsset": ("cutecanvas.coverage.asset", "CoverageAsset"),
    "CoverageAssetSnapshot": (
        "cutecanvas.coverage.asset",
        "CoverageAssetSnapshot",
    ),
    "CoverageDocumentEvaluator": (
        "cutecanvas.coverage.evaluation",
        "CoverageDocumentEvaluator",
    ),
    "CoverageItemMoveSession": (
        "cutecanvas.coverage.movement",
        "CoverageItemMoveSession",
    ),
}

__all__ = [
    "AffineCoverageResampler",
    "CoverageAsset",
    "CoverageAssetSnapshot",
    "CoverageCombineMode",
    "CoverageDocument",
    "CoverageDocumentEvaluator",
    "CoverageEdgeModificationRequest",
    "CoverageFilterCancelledError",
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
    "build_coverage_edge_modification",
    "combine_coverage",
    "dilate_coverage",
    "erode_coverage",
    "feather_coverage",
    "normalize_coverage_array",
    "reframe_coverage_snapshot",
]


def __getattr__(name: str) -> Any:
    """Load higher-level coverage owners only when explicitly requested."""
    target = _DEFERRED_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(target[0]), target[1])
    globals()[name] = value
    return value
