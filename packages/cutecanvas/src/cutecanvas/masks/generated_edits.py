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
"""Apply generated canvas masks through raster-local authoring policy."""

from __future__ import annotations

import uuid

import numpy as np

from .edit_service import MaskEditService
from .projection import MaskCanvasProjectionService
from .render_cache import MaskRenderCache


class MaskGeneratedEditService:
    """Own generated-mask mapping without coupling SAM to mask storage."""

    def __init__(
        self,
        *,
        projection: MaskCanvasProjectionService,
        edits: MaskEditService,
        renders: MaskRenderCache,
    ) -> None:
        """Bind generic generated pixels to authoritative mask edit owners."""
        self._projection = projection
        self._edits = edits
        self._renders = renders

    def apply(
        self,
        mask_id: uuid.UUID,
        incoming_mask: np.ndarray | None,
        *,
        erase: bool,
    ) -> tuple[uuid.UUID, bool] | None:
        """Map and commit generated canvas pixels to one exact mask target."""
        if incoming_mask is None:
            self._renders.invalidate(mask_id)
            return mask_id, False
        snapshot = self._projection.combine_canvas_mask(
            mask_id,
            incoming_mask,
            erase=erase,
        )
        if snapshot is None:
            return mask_id, False
        return mask_id, self._edits.apply_mask_surface(mask_id, snapshot)
