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
"""Commit SAM coverage to its captured pixel-selection target."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from cutecanvas.coverage import CoverageSnapshot, normalize_coverage_array
from cutecanvas.sam.segmentation_request import SmartSegmentationRequest
from cutecanvas.types import RasterExtentPolicy
from qpane.sdk.scene import RasterBounds, SceneDescriptor

from .projection import LayerCoverageProjector
from .service import PixelSelectionService


class SmartSelectionResultCommitter:
    """Project segmented raster coverage into the captured scene selection."""

    def __init__(
        self,
        *,
        active_scene: Callable[[], SceneDescriptor | None],
        selections: PixelSelectionService,
    ) -> None:
        """Bind current scene validation and authoritative selection storage."""
        self._active_scene = active_scene
        self._selections = selections
        self._projector = LayerCoverageProjector()

    def commit(
        self,
        request: SmartSegmentationRequest,
        mask: np.ndarray | None,
    ) -> bool:
        """Commit coverage only while its captured raster instance remains current."""
        if mask is None:
            return False
        scene = self._active_scene()
        if scene is None or scene.scene_id != request.scene_id:
            return False
        layer = next(
            (
                candidate
                for candidate in scene.layers
                if candidate.layer_id == request.layer_id
            ),
            None,
        )
        if (
            layer is None
            or getattr(layer.source, "resource_id", None) != request.resource_id
        ):
            return False
        transform = layer.transform
        if transform is None:
            return False
        pixels = normalize_coverage_array(mask)
        if pixels.size == 0:
            return False
        source = CoverageSnapshot(
            RasterBounds(0, 0, pixels.shape[1], pixels.shape[0]),
            RasterExtentPolicy.FIXED,
            pixels,
        )
        projected = self._projector.project(source, transform)
        if projected is None:
            return False
        return self._selections.commit(
            request.scene_id,
            projected,
            request.combine_mode,
        )


__all__ = ["SmartSelectionResultCommitter"]
