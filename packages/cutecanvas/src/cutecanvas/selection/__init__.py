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
"""Composition-scoped pixel-selection state and geometry."""

from .boundary import SelectionBoundaryBuilder
from .compositor import compose_selection_coverage, trim_selection_coverage
from .geometry import SelectionGeometryRasterizer
from .history import PixelSelectionEdit
from .model import PixelSelectionState
from .modification import (
    PixelSelectionModificationRequest,
    build_pixel_selection_modification,
)
from .modification_coordinator import PixelSelectionModificationCoordinator
from .paint_target import PixelSelectionPaintTargetOwner
from .projection import LayerCoverageProjector
from .service import PixelSelectionService

__all__ = [
    "LayerCoverageProjector",
    "PixelSelectionEdit",
    "PixelSelectionModificationCoordinator",
    "PixelSelectionModificationRequest",
    "PixelSelectionPaintTargetOwner",
    "PixelSelectionService",
    "PixelSelectionState",
    "SelectionBoundaryBuilder",
    "SelectionGeometryRasterizer",
    "build_pixel_selection_modification",
    "compose_selection_coverage",
    "trim_selection_coverage",
]
