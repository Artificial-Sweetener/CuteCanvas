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
"""Track effective source geometry for document-shared mask previews."""

from __future__ import annotations

import uuid
from typing import Protocol

from qpane.sdk.scene import RasterBounds

from .live_preview_store import MaskLivePreviewStore
from .mask import MaskLayer


class _MaskLayerLookup(Protocol):
    """Resolve durable masks without exposing store implementation details."""

    def get_layer(self, mask_id: uuid.UUID) -> MaskLayer | None:
        """Return one mask layer when it exists."""
        ...


class MaskPreviewSceneGeometryTracker:
    """Detect preview-envelope changes that require scene recompilation."""

    def __init__(
        self,
        assets: _MaskLayerLookup,
        previews: MaskLivePreviewStore,
    ) -> None:
        """Bind durable and provisional geometry owners."""
        self._assets = assets
        self._previews = previews
        self._effective_bounds: dict[uuid.UUID, RasterBounds | None] = {}

    def changed(self, mask_id: uuid.UUID) -> bool:
        """Return whether ``mask_id``'s effective source envelope changed."""
        current = self.effective_bounds(mask_id)
        if mask_id not in self._effective_bounds:
            layer = self._assets.get_layer(mask_id)
            previous = None if layer is None else layer.coverage.source_bounds()
        else:
            previous = self._effective_bounds[mask_id]
        if previous == current:
            self._effective_bounds[mask_id] = current
            return False
        self._effective_bounds[mask_id] = current
        return True

    def effective_bounds(self, mask_id: uuid.UUID) -> RasterBounds | None:
        """Return durable bounds united with provisional visible coverage."""
        layer = self._assets.get_layer(mask_id)
        durable = None if layer is None else layer.coverage.source_bounds()
        preview = self._previews.preview(mask_id)
        return durable if preview is None else preview.presentation_bounds(durable)
