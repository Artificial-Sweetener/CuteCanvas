#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Composition-scoped pixel-selection state and geometry."""

from .boundary import SelectionBoundaryBuilder
from .compositor import compose_selection_coverage, trim_selection_coverage
from .geometry import SelectionGeometryRasterizer
from .history import PixelSelectionEdit
from .model import PixelSelectionState
from .projection import LayerCoverageProjector
from .service import PixelSelectionService

__all__ = [
    "LayerCoverageProjector",
    "PixelSelectionEdit",
    "PixelSelectionService",
    "PixelSelectionState",
    "SelectionBoundaryBuilder",
    "SelectionGeometryRasterizer",
    "compose_selection_coverage",
    "trim_selection_coverage",
]
