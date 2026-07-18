#    QPane - High-performance PySide6 image viewer
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

"""Prospective mask union and subtraction operations."""

from __future__ import annotations

import uuid

import numpy as np
from PySide6.QtGui import QImage

from ..catalog.image_utils import numpy_to_qimage_grayscale8
from .image_ops import resize_mask_nearest
from .mask import MaskAssetStore
from .surface import normalize_mask_array


class MaskCombiner:
    """Build uncommitted mask pixels from canonical and incoming arrays."""

    def __init__(self, assets: MaskAssetStore) -> None:
        """Use the asset store as the canonical pixel source."""
        self._assets = assets

    def combine(
        self,
        mask_id: uuid.UUID,
        new_mask: np.ndarray,
        *,
        erase_mode: bool = False,
    ) -> QImage | None:
        """Return combined pixels, or None when the operation is a no-op."""
        layer = self._assets.get_layer(mask_id)
        if layer is None:
            return None
        incoming = normalize_mask_array(new_mask)
        existing = self._assets.get_mask_image_as_numpy(mask_id)
        was_null = layer.surface.is_null()
        if existing is None:
            existing = np.zeros(incoming.shape, dtype=np.uint8)
        elif existing.shape != incoming.shape:
            incoming = resize_mask_nearest(incoming, existing.shape)
        combined = (
            np.bitwise_and(existing, np.bitwise_not(incoming))
            if erase_mode
            else np.bitwise_or(existing, incoming)
        )
        if not was_null and np.array_equal(existing, combined):
            return None
        return numpy_to_qimage_grayscale8(combined)
