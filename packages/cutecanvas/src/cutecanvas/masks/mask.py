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
"""Mask asset storage and pixel access."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
from PySide6.QtGui import QImage

from cutecanvas.coverage import (
    CoverageAsset,
    CoverageAssetSnapshot,
    CoverageItem,
    CoverageSnapshot,
    CoverageStateSnapshot,
    CoverageSurface,
)

from ..composition.edit_controller import CompositionEditController
from ..raster.sparse_grid import SparseRasterSnapshot
from ..resources import ProjectResourceKind, ProjectResourceStore
from .coverage_history import MaskCoverageState
from .history import MaskHistory
from .mask_undo import (
    MaskHistoryChange,
    MaskPatch,
    MaskUndoState,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MaskLayer:
    """Identify one mask asset and own its hybrid authored coverage."""

    mask_id: uuid.UUID
    coverage: CoverageAsset

    def __post_init__(self) -> None:
        """Require one matching hybrid coverage authority."""
        if not isinstance(self.coverage, CoverageAsset):
            raise TypeError("MaskLayer requires a CoverageAsset instance.")
        if self.coverage.asset_id != self.mask_id:
            raise ValueError("mask and coverage asset identities must match")

    @property
    def mask_image(self) -> QImage:
        """Return a detached snapshot of the current mask pixels."""
        return self.coverage.snapshot_qimage()

    @mask_image.setter
    def mask_image(self, image: QImage) -> None:
        """Replace authoritative pixels from ``image``."""
        self.coverage.replace_raster_qimage(image)


class MaskAssetStore:
    """Own mask asset identities and authoritative pixel surfaces."""

    def __init__(
        self,
        resources: ProjectResourceStore,
        *,
        undo_limit: int = 20,
    ) -> None:
        """Initialize asset storage before composition history is bound."""
        self._resources = resources
        self._masks: dict[uuid.UUID, MaskLayer] = {}
        self._history = MaskHistory(
            self,
            undo_limit=undo_limit,
        )
        self._history_subscribers: list[Callable[[MaskHistoryChange], None]] = []

    def get_layer(self, mask_id: uuid.UUID) -> MaskLayer | None:
        """Return one mask asset when it exists."""
        return self._masks.get(mask_id)

    def get_surface(self, mask_id: uuid.UUID) -> CoverageSurface | None:
        """Return authoritative pixel storage for one asset."""
        layer = self._masks.get(mask_id)
        return None if layer is None else layer.coverage.raster

    def mask_ids(self) -> tuple[uuid.UUID, ...]:
        """Return all asset identifiers in creation order."""
        return tuple(self._masks)

    @property
    def undo_limit(self) -> int:
        """Return the history depth applied to mask assets."""
        return self._history.undo_limit

    def set_undo_limit(self, undo_limit: int) -> None:
        """Update history depth for existing and future assets."""
        self._history.set_limit(undo_limit, self.mask_ids())

    def bind_composition_edits(
        self,
        edits: CompositionEditController,
        scope_for_mask: Callable[[uuid.UUID], uuid.UUID | None],
        completed: Callable[[MaskHistoryChange], None],
    ) -> Callable[[], None]:
        """Bind chronology and return an idempotent presentation unsubscribe."""

        if completed not in self._history_subscribers:
            self._history_subscribers.append(completed)
        self._history.bind(edits, scope_for_mask, self._publish_history_change)

        def unsubscribe() -> None:
            """Detach the mounted presentation's history observer."""
            if completed in self._history_subscribers:
                self._history_subscribers.remove(completed)

        return unsubscribe

    def _publish_history_change(self, change: MaskHistoryChange) -> None:
        """Invalidate once, then notify every mounted mask presentation."""
        self._touch(change.mask_id)
        for callback in tuple(self._history_subscribers):
            callback(change)

    def create_mask(self, image: QImage) -> uuid.UUID:
        """Create a blank asset matching ``image`` dimensions."""
        mask_id = uuid.uuid4()
        self._resources.create(
            ProjectResourceKind.COVERAGE,
            editable=True,
            resource_id=mask_id,
        )
        self._masks[mask_id] = MaskLayer(
            mask_id=mask_id,
            coverage=CoverageAsset(mask_id, CoverageSurface.blank(image.size())),
        )
        self._history.initialize_mask(mask_id)
        return mask_id

    def restore_mask(
        self,
        mask_id: uuid.UUID,
        snapshot: CoverageAssetSnapshot | CoverageStateSnapshot,
    ) -> None:
        """Install a validated durable mask snapshot with fresh edit history."""
        if not isinstance(mask_id, uuid.UUID):
            raise TypeError("mask_id must be a UUID")
        if not isinstance(
            snapshot,
            (CoverageAssetSnapshot, CoverageSnapshot, SparseRasterSnapshot),
        ):
            raise TypeError("snapshot must be a coverage asset or raster snapshot")
        if mask_id in self._masks:
            self._history.dispose_mask(mask_id)
        record = self._resources.get(mask_id)
        if record is None:
            self._resources.create(
                ProjectResourceKind.COVERAGE,
                editable=True,
                resource_id=mask_id,
            )
        elif record.kind is not ProjectResourceKind.COVERAGE:
            raise ValueError("mask identity belongs to a non-coverage resource")
        if isinstance(snapshot, CoverageAssetSnapshot):
            coverage = CoverageAsset.from_snapshot(mask_id, snapshot)
        else:
            surface = (
                CoverageSurface.from_sparse_snapshot(snapshot)
                if isinstance(snapshot, SparseRasterSnapshot)
                else CoverageSurface(
                    snapshot.pixels,
                    bounds=snapshot.bounds,
                    extent_policy=snapshot.extent_policy,
                )
            )
            coverage = CoverageAsset(mask_id, surface)
        self._masks[mask_id] = MaskLayer(
            mask_id=mask_id,
            coverage=coverage,
        )
        self._history.initialize_mask(mask_id)

    def delete_mask(self, mask_id: uuid.UUID) -> bool:
        """Delete one asset and its independent history."""
        if mask_id not in self._masks:
            return False
        if self._resources.get(mask_id) is not None:
            self._resources.remove(mask_id)
        self._history.dispose_mask(mask_id)
        del self._masks[mask_id]
        return True

    def fork(self, mask_id: uuid.UUID) -> uuid.UUID | None:
        """Clone one coverage payload into an independent project resource."""
        layer = self._masks.get(mask_id)
        if layer is None:
            return None
        fork_id = uuid.uuid4()
        self._resources.create(
            ProjectResourceKind.COVERAGE,
            editable=True,
            resource_id=fork_id,
        )
        self._masks[fork_id] = MaskLayer(
            mask_id=fork_id,
            coverage=CoverageAsset.from_snapshot(
                fork_id,
                layer.coverage.state_snapshot(),
            ),
        )
        self._history.initialize_mask(fork_id)
        return fork_id

    def commit_mask_patches(
        self,
        mask_id: uuid.UUID,
        patches: Sequence[MaskPatch],
        *,
        notify: Callable[[uuid.UUID], None] | None = None,
    ) -> bool:
        """Commit patch edits through the history owner."""
        changed = self._history.commit_patches(mask_id, patches, notify=notify)
        if changed:
            self._touch(mask_id)
        return changed

    def commit_coverage_item(
        self,
        mask_id: uuid.UUID,
        item: CoverageItem,
        *,
        notify: Callable[[uuid.UUID], None] | None = None,
    ) -> bool:
        """Commit retained mask authorship through composition history."""
        changed = self._history.commit_coverage_item(mask_id, item, notify=notify)
        if changed:
            self._touch(mask_id)
        return changed

    def rasterize_coverage(
        self,
        mask_id: uuid.UUID,
        *,
        notify: Callable[[uuid.UUID], None] | None = None,
    ) -> bool:
        """Flatten retained mask items as one reversible hybrid transition."""
        layer = self._masks.get(mask_id)
        if layer is None or not layer.coverage.has_retained_items:
            return False
        before = MaskCoverageState(
            layer.coverage.raster.state_snapshot(),
            layer.coverage.retained,
        )
        if not layer.coverage.rasterize():
            return False
        after = MaskCoverageState(
            layer.coverage.raster.state_snapshot(),
            layer.coverage.retained,
        )
        changed = self._history.record_applied_coverage(
            mask_id,
            before,
            after,
            notify=notify,
        )
        if changed:
            self._touch(mask_id)
        return changed

    def record_applied_mask_patches(
        self,
        mask_id: uuid.UUID,
        patches: Sequence[MaskPatch],
        *,
        notify: Callable[[uuid.UUID], None] | None = None,
    ) -> bool:
        """Record patches already present on authoritative pixels."""
        changed = self._history.commit_patches(
            mask_id,
            patches,
            notify=notify,
            already_applied=True,
        )
        if changed:
            self._touch(mask_id)
        return changed

    def commit_mask_image(
        self,
        mask_id: uuid.UUID,
        image: QImage,
        *,
        before_image: QImage | None = None,
        notify: Callable[[uuid.UUID], None] | None = None,
    ) -> bool:
        """Commit a full-image edit through the history owner."""
        changed = self._history.commit_image(
            mask_id,
            image,
            before_image=before_image,
            notify=notify,
        )
        if changed:
            self._touch(mask_id)
        return changed

    def record_applied_surface(
        self,
        mask_id: uuid.UUID,
        before: CoverageStateSnapshot,
        after: CoverageStateSnapshot,
        *,
        notify: Callable[[uuid.UUID], None] | None = None,
    ) -> bool:
        """Record an already-applied structural surface transition."""
        changed = self._history.record_applied_surface(
            mask_id,
            before,
            after,
            notify=notify,
        )
        if changed:
            self._touch(mask_id)
        return changed

    def commit_mask_surface(
        self,
        mask_id: uuid.UUID,
        snapshot: CoverageSnapshot,
        *,
        notify: Callable[[uuid.UUID], None] | None = None,
    ) -> bool:
        """Commit complete mask structure and pixels through history."""
        changed = self._history.commit_surface(mask_id, snapshot, notify=notify)
        if changed:
            self._touch(mask_id)
        return changed

    def undo_mask(self, mask_id: uuid.UUID) -> MaskHistoryChange | None:
        """Undo one asset edit."""
        return self._history.undo(mask_id)

    def redo_mask(self, mask_id: uuid.UUID) -> MaskHistoryChange | None:
        """Redo one asset edit."""
        return self._history.redo(mask_id)

    def get_undo_state(self, mask_id: uuid.UUID) -> MaskUndoState | None:
        """Return undo/redo depths for an existing asset."""
        return self._history.state(mask_id)

    def set_mask_image(self, mask_id: uuid.UUID, image: QImage) -> None:
        """Replace authoritative pixels for one asset."""
        layer = self._masks.get(mask_id)
        if layer is None:
            logger.warning("Mask %s not found while setting pixels; skipping.", mask_id)
            return
        layer.coverage.replace_raster_qimage(image)
        self._touch(mask_id)

    def get_mask_image_copy(self, mask_id: uuid.UUID) -> QImage | None:
        """Return a detached QImage snapshot for one asset."""
        layer = self._masks.get(mask_id)
        if layer is None:
            return None
        image = layer.coverage.snapshot_qimage()
        return None if image.isNull() else image

    def get_mask_image_as_numpy(self, mask_id: uuid.UUID) -> np.ndarray | None:
        """Return a detached NumPy snapshot for one asset."""
        layer = self._masks.get(mask_id)
        if layer is None:
            return None
        array = layer.coverage.snapshot_array()
        return None if array.size == 0 else array

    def clear_all(self) -> None:
        """Remove all assets and their history state."""
        for mask_id in self.mask_ids():
            self.delete_mask(mask_id)

    def _touch(self, mask_id: uuid.UUID) -> None:
        """Advance one retained coverage resource and its dependents."""
        self.touch(mask_id)

    def touch(self, mask_id: uuid.UUID) -> None:
        """Advance one directly mutated coverage resource and its dependents."""
        if self._resources.get(mask_id) is not None:
            self._resources.touch(mask_id)
