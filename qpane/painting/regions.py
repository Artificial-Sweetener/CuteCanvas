#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Source-neutral dirty-region planning for resolved brush dabs."""

from __future__ import annotations

import math

from ..scene.raster import RasterBounds
from .model import BrushDab


class BrushDabRegionPlanner:
    """Compute conservative integer regions without knowing target format."""

    def bounds(self, dabs: tuple[BrushDab, ...]) -> RasterBounds | None:
        """Return antialias-safe local bounds for ``dabs``."""
        if not dabs:
            return None
        left = min(math.floor(dab.center[0] - dab.diameter / 2.0 - 1.0) for dab in dabs)
        top = min(math.floor(dab.center[1] - dab.diameter / 2.0 - 1.0) for dab in dabs)
        right = max(math.ceil(dab.center[0] + dab.diameter / 2.0 + 1.0) for dab in dabs)
        bottom = max(
            math.ceil(dab.center[1] + dab.diameter / 2.0 + 1.0) for dab in dabs
        )
        return RasterBounds(left, top, right - left, bottom - top)
