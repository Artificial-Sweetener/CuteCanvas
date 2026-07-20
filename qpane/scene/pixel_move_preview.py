#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Immutable render-facing state for selected-pixel movement previews."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..coverage import CoverageSnapshot
    from .affine import LayerTransform
    from .pixel_fragments import RasterPixelFormat, RasterPixelLift
    from .pixel_transitions import RasterPixelTransition
    from .raster import RasterBounds


@dataclass(frozen=True, slots=True)
class RasterPixelMovePreview:
    """Describe one transient selected-pixel displacement in layer coordinates."""

    session_id: uuid.UUID
    scene_id: uuid.UUID
    layer_id: uuid.UUID
    lift: RasterPixelLift
    cut_source: bool
    settled_transition: RasterPixelTransition | None
    fragment_transform: LayerTransform
    extent_clip_bounds: RasterBounds | None

    @property
    def pixel_format(self) -> RasterPixelFormat:
        """Return the immutable lifted fragment's canonical pixel format."""
        return self.lift.fragment.pixel_format

    @property
    def coverage(self) -> CoverageSnapshot:
        """Return immutable source-local selection coverage for damage mapping."""
        return self.lift.fragment.coverage
