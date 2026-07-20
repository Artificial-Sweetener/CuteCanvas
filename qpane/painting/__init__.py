#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Source-neutral deterministic brush and paint-session primitives."""

from .compositor import BrushCompositor
from .configuration import BrushStrokeCompiler
from .coordinates import BrushSourceCoordinateSession
from .dab_engine import BrushDabEngine
from .model import (
    BrushDab,
    BrushDynamics,
    BrushOperation,
    BrushPreset,
    BrushSample,
    BrushStrokeSegment,
)
from .regions import BrushDabRegionPlanner
from .stroke_session import BrushStrokeSession
from .targets import (
    PaintingCoordinator,
    PaintTargetContext,
    PaintTargetIdentity,
    PaintTargetOwner,
    PaintTargetRegistry,
)
from .tip_cache import BrushTipCache

__all__ = (
    "BrushCompositor",
    "BrushDab",
    "BrushDabEngine",
    "BrushDabRegionPlanner",
    "BrushDynamics",
    "BrushOperation",
    "BrushPreset",
    "BrushSample",
    "BrushSourceCoordinateSession",
    "BrushStrokeCompiler",
    "BrushStrokeSegment",
    "BrushStrokeSession",
    "BrushTipCache",
    "PaintTargetContext",
    "PaintTargetIdentity",
    "PaintTargetOwner",
    "PaintTargetRegistry",
    "PaintingCoordinator",
)
