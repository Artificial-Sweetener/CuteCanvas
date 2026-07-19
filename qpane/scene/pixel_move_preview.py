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
    from .pixel_fragments import RasterPixelFormat
    from .pixel_transitions import RasterPixelTransition


@dataclass(frozen=True, slots=True)
class RasterPixelMovePreview:
    """Describe one transient selected-pixel displacement in layer coordinates."""

    session_id: uuid.UUID
    scene_id: uuid.UUID
    layer_id: uuid.UUID
    coverage: CoverageSnapshot
    transition: RasterPixelTransition
    pixel_format: RasterPixelFormat
    delta_x: int
    delta_y: int
