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
"""Coordinate provisional hybrid flattening around direct mask strokes."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from PySide6.QtCore import QRect

from .mask import MaskAssetStore
from .render_cache import MaskRenderCache


class MixedMaskStrokeCoordinator:
    """Present and finalize brush strokes that follow retained mask tools."""

    def __init__(
        self,
        *,
        assets: MaskAssetStore,
        renders: MaskRenderCache,
        advance_epoch: Callable[[uuid.UUID, str], int],
        structure_changed: Callable[[], None],
        mask_changed: Callable[[uuid.UUID | None, QRect], None],
        undo_changed: Callable[[uuid.UUID], None],
    ) -> None:
        """Bind hybrid authority and its presentation collaborators."""
        self._assets = assets
        self._renders = renders
        self._advance_epoch = advance_epoch
        self._structure_changed = structure_changed
        self._mask_changed = mask_changed
        self._undo_changed = undo_changed

    def begin(self, mask_id: uuid.UUID) -> bool:
        """Flatten retained authorship provisionally for ordered brush pixels."""
        if not self._assets.coverage_edits.begin_mixed_stroke(mask_id):
            return False
        self._refresh(mask_id, reason="mixed_stroke_begin")
        return True

    def active(self, mask_id: uuid.UUID) -> bool:
        """Return whether a mixed-tool transaction owns ``mask_id``."""
        return self._assets.coverage_edits.has_mixed_stroke(mask_id)

    def commit(self, mask_id: uuid.UUID) -> bool:
        """Commit one complete retained-to-raster stroke transition."""
        changed = self._assets.coverage_edits.commit_mixed_stroke(mask_id)
        if changed:
            self._refresh(mask_id, reason="mixed_stroke_commit")
            self._undo_changed(mask_id)
        return changed

    def cancel(self, mask_id: uuid.UUID) -> bool:
        """Restore the exact hybrid state captured before the stroke."""
        changed = self._assets.coverage_edits.cancel_mixed_stroke(mask_id)
        if changed:
            self._refresh(mask_id, reason="mixed_stroke_cancel")
        return changed

    def _refresh(self, mask_id: uuid.UUID, *, reason: str) -> None:
        """Invalidate derived state after a hybrid authority transition."""
        self._advance_epoch(mask_id, reason)
        layer = self._assets.get_layer(mask_id)
        if layer is not None:
            self._renders.invalidate_layer(layer)
        self._structure_changed()
        self._mask_changed(mask_id, QRect())
