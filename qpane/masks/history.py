#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Mask command construction bound to composition-owned chronological history."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

import numpy as np
from PySide6.QtGui import QImage

from ..composition.edit_controller import CompositionEditController
from ..composition.edit_history import CompositionEditCommand
from ..coverage import CoverageSnapshot
from ..raster.image_conversion import qimage_to_numpy_view_grayscale8
from .mask_undo import (
    MaskHistoryChange,
    MaskImageCommand,
    MaskPatch,
    MaskPatchCommand,
    MaskUndoCommand,
    MaskUndoState,
)
from .surface_history import MaskSurfaceCommand

logger = logging.getLogger(__name__)


class CoverageSurfaceLike(Protocol):
    """Surface operations required to construct and replay mask commands."""

    def snapshot(self) -> CoverageSnapshot:
        """Return detached surface structure and pixels."""
        ...

    def snapshot_qimage(self) -> QImage:
        """Return detached pixel imagery."""
        ...

    def is_null(self) -> bool:
        """Return whether the surface has no pixels."""
        ...

    def mutate(self, mutator: Callable[[np.ndarray, QImage], None]) -> None:
        """Apply an in-place pixel mutation."""
        ...

    def replace_with_snapshot(self, snapshot: CoverageSnapshot) -> None:
        """Restore complete surface state."""
        ...


class MaskAssetLike(Protocol):
    """Mask asset state required by history replay."""

    surface: CoverageSurfaceLike


class MaskAssetAccess(Protocol):
    """Asset storage boundary consumed by mask command construction."""

    def get_layer(self, mask_id: uuid.UUID) -> MaskAssetLike | None:
        """Resolve a mask asset."""
        ...

    def get_mask_image_copy(self, mask_id: uuid.UUID) -> QImage | None:
        """Return detached mask pixels."""
        ...

    def set_mask_image(self, mask_id: uuid.UUID, image: QImage) -> None:
        """Replace authoritative mask pixels."""
        ...


@dataclass(frozen=True, slots=True)
class MaskCompositionEdit:
    """Retain one mask-domain command in a composition edit timeline."""

    scene_id: uuid.UUID
    mask_id: uuid.UUID
    command: MaskUndoCommand
    retained_bytes: int
    completed: Callable[[MaskHistoryChange], None] | None = None

    @property
    def scope_id(self) -> uuid.UUID:
        """Return the resolved scene identity owning this edit."""
        return self.scene_id

    def edit_completed(self, direction: Literal["undo", "redo"]) -> None:
        """Publish cache and scene updates after chronology changes."""
        if self.completed is not None:
            change = _history_change(self, direction)
            if change is not None:
                self.completed(change)


class MaskHistory:
    """Build mask commands while composition history owns all chronology."""

    def __init__(self, assets: MaskAssetAccess, *, undo_limit: int = 20) -> None:
        """Bind assets before the composition edit controller is available."""
        self._assets = assets
        self._undo_limit = max(1, int(undo_limit))
        self._edits: CompositionEditController | None = None
        self._scope_for_mask: Callable[[uuid.UUID], uuid.UUID | None] = lambda _id: None
        self._completed: Callable[[MaskHistoryChange], None] | None = None

    @property
    def undo_limit(self) -> int:
        """Return the legacy configuration depth retained for public reporting."""
        return self._undo_limit

    def bind(
        self,
        edits: CompositionEditController,
        scope_for_mask: Callable[[uuid.UUID], uuid.UUID | None],
        completed: Callable[[MaskHistoryChange], None],
    ) -> None:
        """Bind the sole chronological edit owner and mask-to-scene resolver."""
        self._edits = edits
        self._scope_for_mask = scope_for_mask
        self._completed = completed
        edits.register_handler(
            MaskCompositionEdit,
            undo=self._undo_command,
            redo=self._redo_command,
        )

    def initialize_mask(self, mask_id: uuid.UUID) -> None:
        """Require no per-mask stack initialization."""
        return

    def dispose_mask(self, mask_id: uuid.UUID) -> None:
        """Discard retained commands whose source asset was removed."""
        if self._edits is not None:
            self._edits.discard_where(
                lambda command: isinstance(command, MaskCompositionEdit)
                and command.mask_id == mask_id
            )

    def set_limit(self, undo_limit: int, mask_ids: Sequence[uuid.UUID]) -> None:
        """Retain the configured legacy depth while global history enforces budgets."""
        self._undo_limit = max(1, int(undo_limit))

    def commit_patches(
        self,
        mask_id: uuid.UUID,
        patches: Sequence[MaskPatch],
        *,
        notify: Callable[[uuid.UUID], None] | None = None,
        already_applied: bool = False,
    ) -> bool:
        """Apply or record normalized mask patch changes."""
        command = self._build_patch_command(mask_id, patches, notify=notify)
        if command is None:
            return False
        if not already_applied:
            command.redo()
        return self._record(mask_id, command)

    def commit_image(
        self,
        mask_id: uuid.UUID,
        image: QImage,
        *,
        before_image: QImage | None = None,
        notify: Callable[[uuid.UUID], None] | None = None,
    ) -> bool:
        """Apply and record a complete mask image replacement."""
        if self._assets.get_layer(mask_id) is None:
            return False
        before = before_image or self._assets.get_mask_image_copy(mask_id) or QImage()
        command = MaskImageCommand(
            mask_id,
            before.copy(),
            image.copy(),
            self._apply_image,
            notify,
        )
        command.redo()
        return self._record(mask_id, command)

    def record_applied_surface(
        self,
        mask_id: uuid.UUID,
        before: CoverageSnapshot,
        after: CoverageSnapshot,
        *,
        notify: Callable[[uuid.UUID], None] | None = None,
    ) -> bool:
        """Record an already-applied complete surface transition."""
        if _surface_equal(before, after):
            return False
        return self._record(
            mask_id,
            MaskSurfaceCommand(mask_id, before, after, self._apply_surface, notify),
        )

    def commit_surface(
        self,
        mask_id: uuid.UUID,
        after: CoverageSnapshot,
        *,
        notify: Callable[[uuid.UUID], None] | None = None,
    ) -> bool:
        """Apply and record a complete surface transition."""
        layer = self._assets.get_layer(mask_id)
        if layer is None:
            return False
        before = layer.surface.snapshot()
        if _surface_equal(before, after):
            return False
        command = MaskSurfaceCommand(
            mask_id,
            before,
            after,
            self._apply_surface,
            notify,
        )
        command.redo()
        return self._record(mask_id, command)

    def undo(self, mask_id: uuid.UUID) -> MaskHistoryChange | None:
        """Undo the latest composition edit and describe mask deltas when applicable."""
        scope_id = self._scope_for_mask(mask_id)
        if self._edits is None or scope_id is None:
            return None
        execution = self._edits.undo_where(
            scope_id,
            lambda command: isinstance(command, MaskCompositionEdit)
            and command.mask_id == mask_id,
        )
        return _history_change(execution.command, "undo") if execution.changed else None

    def redo(self, mask_id: uuid.UUID) -> MaskHistoryChange | None:
        """Redo the latest composition edit and describe mask deltas when applicable."""
        scope_id = self._scope_for_mask(mask_id)
        if self._edits is None or scope_id is None:
            return None
        execution = self._edits.redo_where(
            scope_id,
            lambda command: isinstance(command, MaskCompositionEdit)
            and command.mask_id == mask_id,
        )
        return _history_change(execution.command, "redo") if execution.changed else None

    def state(self, mask_id: uuid.UUID) -> MaskUndoState | None:
        """Return mask command depths within its composition timeline."""
        if self._assets.get_layer(mask_id) is None:
            return None
        scope_id = self._scope_for_mask(mask_id)
        if self._edits is None or scope_id is None:
            return MaskUndoState(0, 0)
        return MaskUndoState(
            undo_depth=sum(
                isinstance(command, MaskCompositionEdit) and command.mask_id == mask_id
                for command in self._edits.undo_commands(scope_id)
            ),
            redo_depth=sum(
                isinstance(command, MaskCompositionEdit) and command.mask_id == mask_id
                for command in self._edits.redo_commands(scope_id)
            ),
        )

    def _record(self, mask_id: uuid.UUID, command: MaskUndoCommand) -> bool:
        """Record one command when its mask resolves to a composition scope."""
        scope_id = self._scope_for_mask(mask_id)
        if self._edits is None or scope_id is None:
            return True
        self._edits.record_applied(
            MaskCompositionEdit(
                scope_id,
                mask_id,
                command,
                _command_bytes(command),
                self._completed,
            )
        )
        return True

    def _build_patch_command(
        self,
        mask_id: uuid.UUID,
        patches: Sequence[MaskPatch],
        *,
        notify: Callable[[uuid.UUID], None] | None,
    ) -> MaskUndoCommand | None:
        """Build detached patch data for later replay."""
        if self._assets.get_layer(mask_id) is None or not patches:
            return None
        normalized = tuple(
            MaskPatch(
                patch.rect.normalized(),
                patch.before.copy(),
                patch.after.copy(),
                np.array(patch.mask, copy=True, dtype=bool),
            )
            for patch in patches
        )
        return MaskPatchCommand(
            mask_id,
            normalized,
            self._apply_patches,
            notify,
        )

    def _apply_patches(
        self,
        mask_id: uuid.UUID,
        patches: Sequence[MaskPatch],
        use_after: bool,
    ) -> None:
        """Replay retained patches against authoritative coverage."""
        layer = self._assets.get_layer(mask_id)
        if layer is None or layer.surface.is_null():
            return
        sequence = tuple(patches) if use_after else tuple(reversed(patches))

        def mutate(destination: np.ndarray, _image: QImage) -> None:
            """Copy selected patch direction into canonical storage."""
            for patch in sequence:
                destination_slice = destination[
                    patch.rect.top() : patch.rect.top() + patch.rect.height(),
                    patch.rect.left() : patch.rect.left() + patch.rect.width(),
                ]
                source = patch.after if use_after else patch.before
                source_view, _ = qimage_to_numpy_view_grayscale8(source)
                np.copyto(destination_slice, source_view, where=patch.mask)

        layer.surface.mutate(mutate)

    def _apply_image(self, mask_id: uuid.UUID, image: QImage) -> None:
        """Replay a complete image state."""
        self._assets.set_mask_image(mask_id, image)

    def _apply_surface(self, mask_id: uuid.UUID, snapshot: CoverageSnapshot) -> None:
        """Replay complete mask structure and pixels."""
        layer = self._assets.get_layer(mask_id)
        if layer is not None:
            layer.surface.replace_with_snapshot(snapshot)

    @staticmethod
    def _undo_command(command: CompositionEditCommand) -> bool:
        """Undo one retained mask command."""
        if not isinstance(command, MaskCompositionEdit):
            return False
        command.command.undo()
        return True

    @staticmethod
    def _redo_command(command: CompositionEditCommand) -> bool:
        """Redo one retained mask command."""
        if not isinstance(command, MaskCompositionEdit):
            return False
        command.command.redo()
        return True


def _surface_equal(left: CoverageSnapshot, right: CoverageSnapshot) -> bool:
    """Return whether complete coverage surface states match."""
    return (
        left.bounds == right.bounds
        and left.extent_policy is right.extent_policy
        and np.array_equal(left.pixels, right.pixels)
    )


def _command_bytes(command: MaskUndoCommand) -> int:
    """Estimate detached bytes retained exclusively by one mask command."""
    if isinstance(command, MaskPatchCommand):
        return sum(
            patch.before.sizeInBytes() + patch.after.sizeInBytes() + patch.mask.nbytes
            for patch in command.patches
        )
    if isinstance(command, MaskImageCommand):
        return command.before.sizeInBytes() + command.after.sizeInBytes()
    if isinstance(command, MaskSurfaceCommand):
        return command.before.pixels.nbytes + command.after.pixels.nbytes
    return 0


def _history_change(
    command: CompositionEditCommand | None,
    direction: Literal["undo", "redo"],
) -> MaskHistoryChange | None:
    """Build mask-specific presentation details for one generic execution."""
    if not isinstance(command, MaskCompositionEdit):
        return None
    use_after = direction == "redo"
    snippets = command.command.describe_delta(use_after=use_after) or ()
    return MaskHistoryChange(
        command.mask_id,
        direction,
        command.command,
        tuple(snippets),
    )
