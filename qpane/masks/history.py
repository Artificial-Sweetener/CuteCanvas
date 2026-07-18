#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Undo history ownership for mask pixel assets."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Sequence
from typing import Protocol

import numpy as np
from PySide6.QtGui import QImage

from ..catalog.image_utils import qimage_to_numpy_view_grayscale8
from .mask_undo import (
    MaskHistoryChange,
    MaskImageCommand,
    MaskLayerUndoProvider,
    MaskPatch,
    MaskPatchCommand,
    MaskUndoCommand,
    MaskUndoProvider,
    MaskUndoState,
)

logger = logging.getLogger(__name__)


class MaskSurfaceLike(Protocol):
    """Surface operations required to apply history commands."""

    def snapshot_qimage(self) -> QImage:
        """Return a detached pixel snapshot."""
        ...

    def is_null(self) -> bool:
        """Return whether the surface has no pixels."""
        ...

    def mutate(self, mutator: Callable[[np.ndarray, QImage], None]) -> None:
        """Apply an in-place mutation under the surface lock."""
        ...


class MaskAssetLike(Protocol):
    """Mask asset fields required by history."""

    surface: MaskSurfaceLike


class MaskAssetAccess(Protocol):
    """Asset storage boundary consumed by mask history."""

    def get_layer(self, mask_id: uuid.UUID) -> MaskAssetLike | None:
        """Resolve a mask asset."""
        ...

    def get_mask_image_copy(self, mask_id: uuid.UUID) -> QImage | None:
        """Return a detached image snapshot."""
        ...

    def set_mask_image(self, mask_id: uuid.UUID, image: QImage) -> None:
        """Replace authoritative mask pixels."""
        ...


class MaskHistory:
    """Own per-mask undo providers, commands, limits, and replay."""

    def __init__(
        self,
        assets: MaskAssetAccess,
        *,
        undo_limit: int = 20,
        provider: MaskUndoProvider | None = None,
    ) -> None:
        """Bind asset access and initialize the history provider."""
        self._assets = assets
        self._undo_limit = max(1, int(undo_limit))
        self._provider: MaskUndoProvider = provider or MaskLayerUndoProvider()

    @property
    def undo_limit(self) -> int:
        """Return the configured history depth."""
        return self._undo_limit

    @property
    def provider(self) -> MaskUndoProvider:
        """Return the authoritative undo provider."""
        return self._provider

    def initialize_mask(self, mask_id: uuid.UUID) -> None:
        """Initialize history for a newly created asset."""
        layer = self._assets.get_layer(mask_id)
        if layer is None:
            return
        self._provider.initialize_mask(mask_id, layer)
        self._provider.set_limit(mask_id, self._undo_limit)
        capture = getattr(self._provider, "capture_snapshot", None)
        if capture is not None:
            capture(mask_id, layer.surface.snapshot_qimage())

    def dispose_mask(self, mask_id: uuid.UUID) -> None:
        """Discard all history for a removed mask asset."""
        self._provider.dispose_mask(mask_id)

    def set_limit(self, undo_limit: int, mask_ids: Sequence[uuid.UUID]) -> None:
        """Update the limit and trim all registered histories."""
        self._undo_limit = max(1, int(undo_limit))
        for mask_id in mask_ids:
            self._provider.set_limit(mask_id, self._undo_limit)

    def set_provider(
        self,
        provider: MaskUndoProvider | None,
        mask_ids: Sequence[uuid.UUID],
    ) -> None:
        """Replace the provider and initialize it for existing assets."""
        for mask_id in mask_ids:
            self._provider.dispose_mask(mask_id)
        self._provider = provider or MaskLayerUndoProvider()
        for mask_id in mask_ids:
            self.initialize_mask(mask_id)

    def commit_patches(
        self,
        mask_id: uuid.UUID,
        patches: Sequence[MaskPatch],
        *,
        notify: Callable[[uuid.UUID], None] | None = None,
        already_applied: bool = False,
    ) -> bool:
        """Record normalized patch changes for one asset."""
        command = self._build_patch_command(mask_id, patches, notify=notify)
        if command is None:
            return False
        if already_applied:
            self._provider.record_applied(mask_id, command, self._undo_limit)
        else:
            self._provider.submit(mask_id, command, self._undo_limit)
        return True

    def commit_image(
        self,
        mask_id: uuid.UUID,
        image: QImage,
        *,
        before_image: QImage | None = None,
        notify: Callable[[uuid.UUID], None] | None = None,
    ) -> bool:
        """Record and apply a full-image replacement."""
        if self._assets.get_layer(mask_id) is None:
            self._warn_missing(mask_id, "build undo command")
            return False
        before = (
            before_image.copy()
            if before_image is not None
            else self._assets.get_mask_image_copy(mask_id)
        )
        command = MaskImageCommand(
            mask_id=mask_id,
            before=QImage() if before is None else before,
            after=image.copy() if not image.isNull() else QImage(),
            apply=self._apply_image,
            notify=notify,
        )
        self._provider.submit(mask_id, command, self._undo_limit)
        return True

    def undo(self, mask_id: uuid.UUID) -> MaskHistoryChange | None:
        """Undo the latest command for one asset."""
        return self._provider.undo(mask_id)

    def redo(self, mask_id: uuid.UUID) -> MaskHistoryChange | None:
        """Redo the latest reverted command for one asset."""
        return self._provider.redo(mask_id)

    def state(self, mask_id: uuid.UUID) -> MaskUndoState | None:
        """Return current undo/redo depths for an existing asset."""
        if self._assets.get_layer(mask_id) is None:
            return None
        try:
            return self._provider.get_state(mask_id)
        except AttributeError:
            return None

    def _build_patch_command(
        self,
        mask_id: uuid.UUID,
        patches: Sequence[MaskPatch],
        *,
        notify: Callable[[uuid.UUID], None] | None,
    ) -> MaskUndoCommand | None:
        """Build a detached patch command for later replay."""
        if self._assets.get_layer(mask_id) is None:
            self._warn_missing(mask_id, "build undo patch command")
            return None
        if not patches:
            return None
        normalized = tuple(
            MaskPatch(
                rect=patch.rect.normalized(),
                before=patch.before.copy(),
                after=patch.after.copy(),
                mask=np.array(patch.mask, copy=True, dtype=bool),
            )
            for patch in patches
        )
        return MaskPatchCommand(
            mask_id=mask_id,
            patches=normalized,
            apply=self._apply_patches,
            notify=notify,
        )

    def _apply_patches(
        self,
        mask_id: uuid.UUID,
        patches: Sequence[MaskPatch],
        use_after: bool,
    ) -> None:
        """Replay patches against authoritative asset pixels."""
        layer = self._assets.get_layer(mask_id)
        if layer is None or layer.surface.is_null():
            self._warn_missing(mask_id, "apply patch command")
            return
        sequence = tuple(patches) if use_after else tuple(reversed(patches))

        def mutate(destination: np.ndarray, _image: QImage) -> None:
            """Replay the selected patch direction into canonical pixels."""
            for patch in sequence:
                y0 = patch.rect.top()
                x0 = patch.rect.left()
                destination_slice = destination[
                    y0 : y0 + patch.rect.height(),
                    x0 : x0 + patch.rect.width(),
                ]
                source = patch.after if use_after else patch.before
                source_view, _ = qimage_to_numpy_view_grayscale8(source)
                np.copyto(destination_slice, source_view, where=patch.mask)

        layer.surface.mutate(mutate)

    def _apply_image(self, mask_id: uuid.UUID, image: QImage) -> None:
        """Replay a full-image history state."""
        self._assets.set_mask_image(mask_id, image)

    @staticmethod
    def _warn_missing(mask_id: uuid.UUID, action: str) -> None:
        """Log an ignored history operation for a missing asset."""
        logger.warning(
            "Mask %s not found while attempting to %s; skipping.", mask_id, action
        )
