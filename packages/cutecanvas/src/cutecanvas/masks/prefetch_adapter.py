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
"""Adapt mask derived-raster warming to generic scene prefetching."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from .mask_service import MaskService


@dataclass(frozen=True, slots=True)
class MaskScenePrefetcher:
    """Provide mask source warming through the swap-neutral protocol."""

    service: MaskService

    def has_sources(self, image_id: uuid.UUID) -> bool:
        """Return whether the image scene contains mask sources."""
        return bool(self.service.mask_ids_for_image(image_id))

    def prefetch(
        self,
        image_id: uuid.UUID,
        *,
        reason: str = "navigation",
        scales: Sequence[float] | None = None,
    ) -> bool:
        """Warm derived mask rasters for one image scene."""
        return self.service.prefetchColorizedMasks(
            image_id,
            reason=reason,
            scales=scales,
        )

    def cancel(self, image_id: uuid.UUID | None) -> bool:
        """Cancel derived-raster warming for one or every image scene."""
        return self.service.cancelPrefetch(image_id)
