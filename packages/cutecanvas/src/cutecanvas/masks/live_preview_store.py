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

"""Share native provisional mask coverage across document views."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QObject, QRect, Signal
from PySide6.QtGui import QImage
from qpane.sdk.scene import RasterBounds

from .live_preview_raster import LiveMaskPreviewPatches


class MaskLivePreviewStore(QObject):
    """Own document-scoped provisional mask patches and their invalidation."""

    changed = Signal(object, QRect)

    def __init__(self) -> None:
        """Create an empty document-scoped preview registry."""
        super().__init__()
        self._previews: dict[uuid.UUID, LiveMaskPreviewPatches] = {}

    def preview(self, mask_id: uuid.UUID) -> LiveMaskPreviewPatches | None:
        """Return the current native provisional coverage for one mask."""
        return self._previews.get(mask_id)

    def contains(self, mask_id: uuid.UUID) -> bool:
        """Return whether one mask has shared provisional coverage."""
        return mask_id in self._previews

    def apply_patch(
        self,
        mask_id: uuid.UUID,
        source_bounds: RasterBounds,
        storage_rect: QRect,
        patch: QImage,
    ) -> None:
        """Publish one native patch and notify every mounted document view."""
        preview = self._previews.get(mask_id)
        if preview is None or preview.source_bounds != source_bounds:
            preview = LiveMaskPreviewPatches(source_bounds)
            self._previews[mask_id] = preview
        preview.apply_patch(storage_rect, patch)
        self.changed.emit(mask_id, QRect(storage_rect))

    def discard(self, mask_id: uuid.UUID) -> bool:
        """Remove one provisional source and publish its full invalidation."""
        if self._previews.pop(mask_id, None) is None:
            return False
        self.changed.emit(mask_id, QRect())
        return True

    def clear(self) -> None:
        """Release every preview when its document runtime closes."""
        self._previews.clear()


__all__ = ["MaskLivePreviewStore"]
