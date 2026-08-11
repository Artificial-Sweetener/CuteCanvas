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
from qpane.sdk.raster import qimage_to_numpy_grayscale8

if TYPE_CHECKING:
    from PySide6.QtGui import QImage
    from qpane.sdk.scene import RasterBounds


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
    """Represent a storage patch with stable layer-local replay bounds."""

    rect: QRect
    before: QImage
    after: QImage
    mask: NDArray[np.bool_]
    bounds: RasterBounds | None = None


@dataclass
class MaskPatchCommand:
    """Undo command that reapplies a collection of mask patches."""

    mask_id: uuid.UUID
    patches: Sequence[MaskPatch]
    apply: Callable[[uuid.UUID, Sequence[MaskPatch], bool], None]
    resolve_rect: Callable[[uuid.UUID, MaskPatch], QRect | None]
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
            rect = self.resolve_rect(self.mask_id, patch)
            if image.isNull() or rect is None:
                continue
            payload.append(MaskUndoSnippet(rect=rect, image=image))
        if not payload:
            return None
        return tuple(payload)
