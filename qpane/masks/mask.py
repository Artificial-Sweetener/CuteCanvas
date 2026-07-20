#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Mask asset storage and pixel access."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
from PySide6.QtGui import QImage

from ..composition.edit_controller import CompositionEditController
from ..coverage import CoverageSnapshot, CoverageStateSnapshot, CoverageSurface
from ..raster.sparse_grid import SparseRasterSnapshot
from .history import MaskHistory
from .mask_undo import (
    MaskHistoryChange,
    MaskPatch,
    MaskUndoState,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MaskLayer:
    """Identify one mask asset and expose detached pixel snapshots."""

    mask_id: uuid.UUID
    surface: CoverageSurface

    def __post_init__(self) -> None:
        """Require authoritative storage for every mask asset."""
        if not isinstance(self.surface, CoverageSurface):
            raise TypeError("MaskLayer requires a CoverageSurface instance.")

    @property
    def mask_image(self) -> QImage:
        """Return a detached snapshot of the current mask pixels."""
        return self.surface.snapshot_qimage()

    @mask_image.setter
    def mask_image(self, image: QImage) -> None:
        """Replace authoritative pixels from ``image``."""
        self.surface.replace_with_qimage(image)


class MaskAssetStore:
    """Own mask asset identities and authoritative pixel surfaces."""

    def __init__(
        self,
        *,
        undo_limit: int = 20,
    ) -> None:
        """Initialize asset storage before composition history is bound."""
        self._masks: dict[uuid.UUID, MaskLayer] = {}
        self._history = MaskHistory(
            self,
            undo_limit=undo_limit,
        )

    def get_layer(self, mask_id: uuid.UUID) -> MaskLayer | None:
        """Return one mask asset when it exists."""
        return self._masks.get(mask_id)

    def get_surface(self, mask_id: uuid.UUID) -> CoverageSurface | None:
        """Return authoritative pixel storage for one asset."""
        layer = self._masks.get(mask_id)
        return None if layer is None else layer.surface

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
    ) -> None:
        """Bind mask commands to the authoritative composition timeline."""
        self._history.bind(edits, scope_for_mask, completed)

    def create_mask(self, image: QImage) -> uuid.UUID:
        """Create a blank asset matching ``image`` dimensions."""
        mask_id = uuid.uuid4()
        self._masks[mask_id] = MaskLayer(
            mask_id=mask_id,
            surface=CoverageSurface.blank(image.size()),
        )
        self._history.initialize_mask(mask_id)
        return mask_id

    def restore_mask(
        self,
        mask_id: uuid.UUID,
        snapshot: CoverageStateSnapshot,
    ) -> None:
        """Install a validated durable mask snapshot with fresh edit history."""
        if not isinstance(mask_id, uuid.UUID):
            raise TypeError("mask_id must be a UUID")
        if not isinstance(snapshot, (CoverageSnapshot, SparseRasterSnapshot)):
            raise TypeError("snapshot must be a coverage state snapshot")
        if mask_id in self._masks:
            self._history.dispose_mask(mask_id)
        surface = (
            CoverageSurface.from_sparse_snapshot(snapshot)
            if isinstance(snapshot, SparseRasterSnapshot)
            else CoverageSurface(
                snapshot.pixels,
                bounds=snapshot.bounds,
                extent_policy=snapshot.extent_policy,
            )
        )
        self._masks[mask_id] = MaskLayer(mask_id=mask_id, surface=surface)
        self._history.initialize_mask(mask_id)

    def delete_mask(self, mask_id: uuid.UUID) -> bool:
        """Delete one asset and its independent history."""
        if mask_id not in self._masks:
            return False
        self._history.dispose_mask(mask_id)
        del self._masks[mask_id]
        return True

    def commit_mask_patches(
        self,
        mask_id: uuid.UUID,
        patches: Sequence[MaskPatch],
        *,
        notify: Callable[[uuid.UUID], None] | None = None,
    ) -> bool:
        """Commit patch edits through the history owner."""
        return self._history.commit_patches(mask_id, patches, notify=notify)

    def record_applied_mask_patches(
        self,
        mask_id: uuid.UUID,
        patches: Sequence[MaskPatch],
        *,
        notify: Callable[[uuid.UUID], None] | None = None,
    ) -> bool:
        """Record patches already present on authoritative pixels."""
        return self._history.commit_patches(
            mask_id,
            patches,
            notify=notify,
            already_applied=True,
        )

    def commit_mask_image(
        self,
        mask_id: uuid.UUID,
        image: QImage,
        *,
        before_image: QImage | None = None,
        notify: Callable[[uuid.UUID], None] | None = None,
    ) -> bool:
        """Commit a full-image edit through the history owner."""
        return self._history.commit_image(
            mask_id,
            image,
            before_image=before_image,
            notify=notify,
        )

    def record_applied_surface(
        self,
        mask_id: uuid.UUID,
        before: CoverageStateSnapshot,
        after: CoverageStateSnapshot,
        *,
        notify: Callable[[uuid.UUID], None] | None = None,
    ) -> bool:
        """Record an already-applied structural surface transition."""
        return self._history.record_applied_surface(
            mask_id,
            before,
            after,
            notify=notify,
        )

    def commit_mask_surface(
        self,
        mask_id: uuid.UUID,
        snapshot: CoverageSnapshot,
        *,
        notify: Callable[[uuid.UUID], None] | None = None,
    ) -> bool:
        """Commit complete mask structure and pixels through history."""
        return self._history.commit_surface(mask_id, snapshot, notify=notify)

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
        layer.surface.replace_with_qimage(image)

    def get_mask_image_copy(self, mask_id: uuid.UUID) -> QImage | None:
        """Return a detached QImage snapshot for one asset."""
        layer = self._masks.get(mask_id)
        if layer is None:
            return None
        image = layer.surface.snapshot_qimage()
        return None if image.isNull() else image

    def get_mask_image_as_numpy(self, mask_id: uuid.UUID) -> np.ndarray | None:
        """Return a detached NumPy snapshot for one asset."""
        layer = self._masks.get(mask_id)
        if layer is None:
            return None
        array = layer.surface.snapshot_array()
        return None if array.size == 0 else array

    def clear_all(self) -> None:
        """Remove all assets and their history state."""
        for mask_id in self.mask_ids():
            self._history.dispose_mask(mask_id)
        self._masks.clear()
