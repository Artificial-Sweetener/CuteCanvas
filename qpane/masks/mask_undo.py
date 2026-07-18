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

"""Undo provider abstractions for mask editing workflows."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Literal,
    Protocol,
)

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import QRect

from ..catalog.image_utils import qimage_to_numpy_grayscale8

if TYPE_CHECKING:
    from PySide6.QtGui import QImage

    from .mask import MaskLayer


@dataclass(frozen=True)
class MaskUndoState:
    """Represent the current undo/redo stack depth for a mask."""

    undo_depth: int
    redo_depth: int

    @property
    def can_undo(self) -> bool:
        """Return True when undo history is available."""
        return self.undo_depth > 0

    @property
    def can_redo(self) -> bool:
        """Return True when redo history is available."""
        return self.redo_depth > 0


@dataclass(frozen=True)
class MaskUndoSnippet:
    """Describe a rectangular snippet affected by a mask history change."""

    rect: QRect
    image: QImage


@dataclass(frozen=True)
class MaskHistoryChange:
    """Capture the outcome of an undo or redo operation."""

    mask_id: uuid.UUID
    direction: Literal["undo", "redo"]
    command: MaskUndoCommand
    snippets: tuple[MaskUndoSnippet, ...] = ()

    @property
    def has_snippets(self) -> bool:
        """Return True when the change exposes localized repaint data."""
        return bool(self.snippets)


class MaskUndoCommand(Protocol):
    """Describe an undoable mask operation."""

    description: str

    def undo(self) -> None:
        """Revert the command's effects."""

    def redo(self) -> None:
        """Apply the command's effects."""

    def describe_delta(self, *, use_after: bool) -> Iterable[MaskUndoSnippet] | None:
        """Return the snippets touched when replaying this command."""


class MaskUndoProvider(Protocol):
    """Define the hooks required to integrate mask undo/redo workflows."""

    def initialize_mask(self, mask_id: uuid.UUID, layer: MaskLayer) -> None:
        """Prepare provider state for ``mask_id`` using the current layer."""

    def dispose_mask(self, mask_id: uuid.UUID) -> None:
        """Release any provider state associated with ``mask_id``."""

    def submit(self, mask_id: uuid.UUID, command: MaskUndoCommand, limit: int) -> None:
        """Record ``command`` for ``mask_id`` and execute it immediately."""

    def record_applied(
        self,
        mask_id: uuid.UUID,
        command: MaskUndoCommand,
        limit: int,
    ) -> None:
        """Record ``command`` after its mutation has already been applied."""

    def undo(self, mask_id: uuid.UUID) -> MaskHistoryChange | None:
        """Undo the latest change for ``mask_id`` when available."""

    def redo(self, mask_id: uuid.UUID) -> MaskHistoryChange | None:
        """Redo the previously undone change for ``mask_id`` when available."""

    def set_limit(self, mask_id: uuid.UUID, limit: int) -> None:
        """Update the retained history depth for ``mask_id``."""

    def get_state(self, mask_id: uuid.UUID) -> MaskUndoState:
        """Return the current undo/redo depth for ``mask_id``."""


@dataclass
class MaskImageCommand:
    """Concrete command that swaps mask images with cache notifications."""

    mask_id: uuid.UUID
    before: QImage
    after: QImage
    apply: Callable[[uuid.UUID, QImage], None]
    notify: Callable[[uuid.UUID], None] | None = None
    description: str = "mask-change"

    def undo(self) -> None:
        """Restore the previous mask image and notify listeners."""
        self.apply(self.mask_id, self.before.copy())
        if self.notify is not None:
            self.notify(self.mask_id)

    def redo(self) -> None:
        """Reapply the new mask image and notify listeners."""
        self.apply(self.mask_id, self.after.copy())
        if self.notify is not None:
            self.notify(self.mask_id)

    def describe_delta(self, *, use_after: bool) -> Iterable[MaskUndoSnippet] | None:
        """Return the changed region between before/after for history previews."""
        target = self.after if use_after else self.before
        other = self.before if use_after else self.after
        if target.isNull():
            return None
        if other.isNull() or target.size() != other.size():
            return (MaskUndoSnippet(rect=target.rect(), image=target.copy()),)
        target_np = qimage_to_numpy_grayscale8(target)
        other_np = qimage_to_numpy_grayscale8(other)
        diff_mask = target_np != other_np
        if not np.any(diff_mask):
            return None
        ys, xs = np.nonzero(diff_mask)
        min_y = int(ys.min())
        max_y = int(ys.max())
        min_x = int(xs.min())
        max_x = int(xs.max())
        width = max_x - min_x + 1
        height = max_y - min_y + 1
        rect = QRect(min_x, min_y, width, height)
        snippet = target.copy(rect)
        return (MaskUndoSnippet(rect=rect, image=snippet),)


@dataclass(slots=True)
class MaskPatch:
    """Represent a rectangular patch captured from a mask stroke."""

    rect: QRect
    before: QImage
    after: QImage
    mask: NDArray[np.bool_]


@dataclass
class MaskPatchCommand:
    """Undo command that reapplies a collection of mask patches."""

    mask_id: uuid.UUID
    patches: Sequence[MaskPatch]
    apply: Callable[[uuid.UUID, Sequence[MaskPatch], bool], None]
    notify: Callable[[uuid.UUID], None] | None = None
    description: str = "mask-change"

    def undo(self) -> None:
        """Replay patches using their ``before`` data."""
        self.apply(self.mask_id, self.patches, False)
        if self.notify is not None:
            self.notify(self.mask_id)

    def redo(self) -> None:
        """Replay patches using their ``after`` data."""
        self.apply(self.mask_id, self.patches, True)
        if self.notify is not None:
            self.notify(self.mask_id)

    def describe_delta(self, *, use_after: bool) -> Iterable[MaskUndoSnippet] | None:
        """Summarize per-patch imagery for history thumbnails."""
        payload: list[MaskUndoSnippet] = []
        for patch in self.patches:
            image = patch.after if use_after else patch.before
            if image.isNull():
                continue
            payload.append(MaskUndoSnippet(rect=patch.rect, image=image))
        if not payload:
            return None
        return tuple(payload)


class MaskLayerUndoProvider:
    """Default provider storing undoable commands in memory."""

    def __init__(self) -> None:
        """Initialize in-memory stacks for undo/redo tracking."""
        self._history: dict[uuid.UUID, list[MaskUndoCommand]] = {}
        self._redos: dict[uuid.UUID, list[MaskUndoCommand]] = {}
        self._baselines: dict[uuid.UUID, QImage] = {}

    def initialize_mask(self, mask_id: uuid.UUID, layer: MaskLayer) -> None:
        """Prepare provider state for ``mask_id`` using ``layer``'s snapshot."""
        self._history[mask_id] = []
        self._redos[mask_id] = []
        self._baselines[mask_id] = layer.surface.snapshot_qimage()

    def dispose_mask(self, mask_id: uuid.UUID) -> None:
        """Release cached history for ``mask_id``."""
        self._history.pop(mask_id, None)
        self._redos.pop(mask_id, None)
        self._baselines.pop(mask_id, None)

    def submit(self, mask_id: uuid.UUID, command: MaskUndoCommand, limit: int) -> None:
        """Execute ``command`` and push it on the undo stack."""
        command.redo()
        self.record_applied(mask_id, command, limit)

    def record_applied(
        self,
        mask_id: uuid.UUID,
        command: MaskUndoCommand,
        limit: int,
    ) -> None:
        """Push an already-applied command without replaying its mutation."""
        history = self._history.setdefault(mask_id, [])
        history.append(command)
        self._redos[mask_id] = []
        self._enforce_limit(mask_id, limit)

    def undo(self, mask_id: uuid.UUID) -> MaskHistoryChange | None:
        """Undo the latest command for ``mask_id`` when available."""
        history = self._history.get(mask_id)
        if not history:
            return None
        command = history.pop()
        command.undo()
        self._redos.setdefault(mask_id, []).append(command)
        snippets = self._describe_command_delta(command, use_after=False)
        return MaskHistoryChange(
            mask_id=mask_id,
            direction="undo",
            command=command,
            snippets=snippets,
        )

    def redo(self, mask_id: uuid.UUID) -> MaskHistoryChange | None:
        """Replay the previously undone command for ``mask_id``."""
        redo_stack = self._redos.get(mask_id)
        if not redo_stack:
            return None
        command = redo_stack.pop()
        command.redo()
        self._history.setdefault(mask_id, []).append(command)
        snippets = self._describe_command_delta(command, use_after=True)
        return MaskHistoryChange(
            mask_id=mask_id,
            direction="redo",
            command=command,
            snippets=snippets,
        )

    def set_limit(self, mask_id: uuid.UUID, limit: int) -> None:
        """Clamp the retained history for ``mask_id`` to ``limit`` entries."""
        self._enforce_limit(mask_id, limit)

    def get_state(self, mask_id: uuid.UUID) -> MaskUndoState:
        """Return the current undo/redo depth for ``mask_id``."""
        history = self._history.get(mask_id) or []
        redo_stack = self._redos.get(mask_id) or []
        return MaskUndoState(undo_depth=len(history), redo_depth=len(redo_stack))

    def capture_snapshot(self, mask_id: uuid.UUID, image: QImage) -> None:
        """Store the current image as the provider baseline."""
        self._baselines[mask_id] = image.copy()

    def _enforce_limit(self, mask_id: uuid.UUID, limit: int) -> None:
        """Trim oldest history entries when exceeding ``limit``."""
        if limit <= 0:
            return
        history = self._history.get(mask_id)
        if not history:
            return
        excess = len(history) - limit
        if excess > 0:
            del history[0:excess]

    def _describe_command_delta(
        self, command: MaskUndoCommand, *, use_after: bool
    ) -> tuple[MaskUndoSnippet, ...]:
        """Return a normalized tuple of snippets from the command if available."""
        describe = getattr(command, "describe_delta", None)
        if describe is None:
            return ()
        data = describe(use_after=use_after)
        if not data:
            return ()
        return tuple(data)
