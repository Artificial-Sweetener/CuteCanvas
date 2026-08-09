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
"""Own atomic edits spanning raster and retained mask coverage."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Protocol

from cutecanvas.coverage import CoverageAsset, CoverageItem, CoverageSnapshot

from .coverage_history import MaskCoverageState
from .history import MaskHistory


class CoverageLayer(Protocol):
    """Expose the hybrid coverage authority required by transactions."""

    coverage: CoverageAsset


class MaskCoverageTransactions:
    """Commit retained authorship and mixed-tool strokes as atomic revisions."""

    def __init__(
        self,
        *,
        layer: Callable[[uuid.UUID], CoverageLayer | None],
        history: MaskHistory,
        changed: Callable[[uuid.UUID], None],
    ) -> None:
        """Bind asset access, chronology, and resource revision publication."""
        self._layer = layer
        self._history = history
        self._changed = changed
        self._stroke_before: dict[uuid.UUID, MaskCoverageState] = {}

    def commit_item(
        self,
        mask_id: uuid.UUID,
        item: CoverageItem,
        *,
        notify: Callable[[uuid.UUID], None] | None = None,
    ) -> bool:
        """Commit one retained item and publish its resource revision."""
        changed = self._history.commit_coverage_item(mask_id, item, notify=notify)
        if changed:
            self._changed(mask_id)
        return changed

    def rasterize(
        self,
        mask_id: uuid.UUID,
        *,
        notify: Callable[[uuid.UUID], None] | None = None,
    ) -> bool:
        """Flatten retained authorship as one reversible explicit edit."""
        layer = self._layer(mask_id)
        if layer is None or not layer.coverage.has_retained_items:
            return False
        before = self._state(layer)
        if not layer.coverage.rasterize():
            return False
        layer.coverage.compact_raster_storage()
        changed = self._history.record_applied_coverage(
            mask_id,
            before,
            self._state(layer),
            notify=notify,
        )
        if changed:
            self._changed(mask_id)
        return changed

    def commit_surface(
        self,
        mask_id: uuid.UUID,
        snapshot: CoverageSnapshot,
        *,
        notify: Callable[[uuid.UUID], None] | None = None,
    ) -> bool:
        """Replace evaluated coverage and clear superseded retained authorship."""
        layer = self._layer(mask_id)
        if layer is None:
            return False
        before = self._state(layer)
        layer.coverage.raster.replace_with_snapshot(snapshot)
        layer.coverage.restore_retained(layer.coverage.retained.clear())
        changed = self._history.record_applied_coverage(
            mask_id,
            before,
            self._normalized_state(layer),
            notify=notify,
        )
        if changed:
            self._changed(mask_id)
        return changed

    def replace_spatial_authority(
        self,
        mask_id: uuid.UUID,
        snapshot: CoverageSnapshot,
    ) -> bool:
        """Replace equivalent mapped authorship without creating a history step."""
        layer = self._layer(mask_id)
        if layer is None:
            return False
        layer.coverage.raster.replace_with_snapshot(snapshot)
        layer.coverage.restore_retained(layer.coverage.retained.clear())
        layer.coverage.compact_raster_storage()
        self._changed(mask_id)
        return True

    def begin_mixed_stroke(self, mask_id: uuid.UUID) -> bool:
        """Flatten retained work provisionally before a raster brush stroke."""
        layer = self._layer(mask_id)
        if (
            layer is None
            or not layer.coverage.has_retained_items
            or mask_id in self._stroke_before
        ):
            return False
        self._stroke_before[mask_id] = self._state(layer)
        if layer.coverage.rasterize():
            return True
        self._stroke_before.pop(mask_id, None)
        return False

    def has_mixed_stroke(self, mask_id: uuid.UUID) -> bool:
        """Return whether ``mask_id`` has a provisional hybrid transaction."""
        return mask_id in self._stroke_before

    def commit_mixed_stroke(self, mask_id: uuid.UUID) -> bool:
        """Record the complete pre-shape to post-brush transition once."""
        before = self._stroke_before.pop(mask_id, None)
        layer = self._layer(mask_id)
        if before is None or layer is None:
            return False
        changed = self._history.record_applied_coverage(
            mask_id,
            before,
            self._normalized_state(layer),
        )
        if changed:
            self._changed(mask_id)
        return changed

    def cancel_mixed_stroke(self, mask_id: uuid.UUID) -> bool:
        """Restore exact retained and raster state after a cancelled gesture."""
        before = self._stroke_before.pop(mask_id, None)
        layer = self._layer(mask_id)
        if before is None or layer is None:
            return False
        layer.coverage.raster.replace_with_state_snapshot(before.raster)
        layer.coverage.restore_retained(before.retained)
        self._changed(mask_id)
        return True

    def discard(self, mask_id: uuid.UUID) -> None:
        """Forget transaction state for a deleted asset."""
        self._stroke_before.pop(mask_id, None)

    @staticmethod
    def _state(layer: CoverageLayer) -> MaskCoverageState:
        """Capture one detached complete hybrid revision."""
        return MaskCoverageState(
            layer.coverage.raster.state_snapshot(),
            layer.coverage.retained,
        )

    @classmethod
    def _normalized_state(cls, layer: CoverageLayer) -> MaskCoverageState:
        """Compact derived allocation before capturing a committed revision."""
        layer.coverage.compact_raster_storage()
        return cls._state(layer)
