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
"""Source-neutral deterministic brush and paint-session primitives."""

from importlib import import_module
from typing import TYPE_CHECKING, Any

from .clone_model import (
    CloneStampAlignment,
    CloneStampSampleMode,
    CloneStampSource,
    CloneStampState,
    CloneStampTransform,
)
from .compositor import BrushCompositor
from .configuration import BrushStrokeCompiler
from .dab_engine import BrushDabEngine
from .model import (
    BrushDab,
    BrushDynamics,
    BrushOperation,
    BrushPreset,
    BrushSample,
    BrushStrokeSegment,
)
from .operations import BrushStrokeOperation, DirectBrushStrokeOperation
from .regions import BrushDabRegionPlanner
from .stroke_session import BrushStrokeSession
from .target_contracts import (
    CoverageFillTargetOwner,
    FloodFillSource,
    FloodFillTargetOwner,
    PaintTargetContext,
    PaintTargetIdentity,
    PaintTargetOwner,
    PaintTargetRegistry,
    RetainedCoverageTargetOwner,
)
from .tip_cache import BrushTipCache
from .tip_preview import BrushTipPreviewRenderer

if TYPE_CHECKING:
    from .targets import PaintingCoordinator

_TARGET_EXPORTS = {
    "PaintingCoordinator",
}

__all__ = (
    "BrushCompositor",
    "BrushDab",
    "BrushDabEngine",
    "BrushDabRegionPlanner",
    "BrushDynamics",
    "BrushOperation",
    "BrushPreset",
    "BrushSample",
    "BrushStrokeCompiler",
    "BrushStrokeOperation",
    "BrushStrokeSegment",
    "BrushStrokeSession",
    "BrushTipCache",
    "BrushTipPreviewRenderer",
    "CloneStampAlignment",
    "CloneStampSampleMode",
    "CloneStampSource",
    "CloneStampState",
    "CloneStampTransform",
    "CoverageFillTargetOwner",
    "DirectBrushStrokeOperation",
    "FloodFillSource",
    "FloodFillTargetOwner",
    "PaintTargetContext",
    "PaintTargetIdentity",
    "PaintTargetOwner",
    "PaintTargetRegistry",
    "PaintingCoordinator",
    "RetainedCoverageTargetOwner",
)


def __getattr__(name: str) -> Any:
    """Load stateful target coordination only when explicitly requested."""
    if name not in _TARGET_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module("cutecanvas.painting.targets"), name)
    globals()[name] = value
    return value
