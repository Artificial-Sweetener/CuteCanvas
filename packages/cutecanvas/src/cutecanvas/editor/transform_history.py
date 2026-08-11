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
"""Own bounded checkpoint history for one unresolved affine transform."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from qpane.sdk.scene import LayerMapping

from cutecanvas.edit_sessions import EditSessionKind

from .provisional_history import (
    BoundedProvisionalHistory,
    ProvisionalHistorySnapshot,
)
from .session_coordination import EditSessionCoordinator


class TransformProvisionalSession:
    """Retain affine checkpoints while delegating transform semantics."""

    def __init__(
        self,
        *,
        sessions: EditSessionCoordinator,
        restore: Callable[[LayerMapping], bool],
        apply_transform: Callable[[], bool],
        cancel_transform: Callable[[], bool],
        suspend_transform: Callable[[], bool],
    ) -> None:
        """Bind generic bounded history to focused affine lifecycle commands."""
        self._sessions = sessions
        self._restore = restore
        self._apply_transform = apply_transform
        self._cancel_transform = cancel_transform
        self._suspend_transform = suspend_transform
        self._session_id: uuid.UUID | None = None
        self._history: BoundedProvisionalHistory[LayerMapping] | None = None
        self._gesture_active = False

    @property
    def active(self) -> bool:
        """Return whether one affine base remains unresolved."""
        return self._session_id is not None and self._history is not None

    @property
    def session_id(self) -> uuid.UUID | None:
        """Return the unresolved affine session identity."""
        return self._session_id

    @property
    def session_kind(self) -> EditSessionKind:
        """Return the public affine session kind."""
        return EditSessionKind.TRANSFORM

    @property
    def session_tool_mode(self) -> str:
        """Return the public Transform tool mode."""
        return "transform"

    @property
    def gesture_active(self) -> bool:
        """Return whether direct pointer input owns the affine session."""
        return self._gesture_active

    @property
    def can_apply(self) -> bool:
        """Return whether the settled affine preview can be applied."""
        return self.active and not self._gesture_active

    @property
    def can_cancel(self) -> bool:
        """Return whether the unresolved affine session can be cancelled."""
        return self.active

    @property
    def provisional_history(self) -> ProvisionalHistorySnapshot | None:
        """Return bounded affine checkpoint state while unresolved."""
        return None if self._history is None else self._history.snapshot

    def begin(self, base: LayerMapping) -> bool:
        """Claim a session rooted at the exact original affine mapping."""
        if self.active:
            return True
        self._session_id = uuid.uuid4()
        self._history = BoundedProvisionalHistory(
            base,
            checkpoint_limit=self._sessions.policy.checkpoint_limit,
        )
        if self._sessions.claim(self):
            return True
        self._session_id = None
        self._history = None
        return False

    def begin_gesture(self) -> None:
        """Publish direct pointer ownership without creating a checkpoint."""
        if not self.active:
            raise RuntimeError("transform gesture requires an active session")
        self._gesture_active = True
        self._sessions.notify_changed()

    def settle(self, value: LayerMapping, label: str) -> bool:
        """Record one completed semantic transform and release pointer ownership."""
        history = self._history
        if history is None:
            return False
        self._gesture_active = False
        changed = history.push(value, label)
        self._sessions.notify_changed()
        return changed

    def undo_provisional(self) -> bool:
        """Restore the previous retained affine checkpoint."""
        history = self._history
        value = None if history is None else history.undo()
        return self._restore_value(value)

    def redo_provisional(self) -> bool:
        """Restore the next retained affine checkpoint."""
        history = self._history
        value = None if history is None else history.redo()
        return self._restore_value(value)

    def apply(self) -> bool:
        """Commit the latest affine preview and discard provisional history."""
        if not self.can_apply:
            return False
        changed = self._apply_transform()
        self._close()
        return changed

    def cancel(self) -> bool:
        """Restore the affine base and discard provisional history."""
        if not self.active:
            return False
        changed = self._cancel_transform()
        self._close()
        return changed

    def suspend(self) -> bool:
        """Release pointer ownership while retaining affine checkpoints."""
        if not self.active:
            return False
        changed = self._suspend_transform()
        self._gesture_active = False
        self._sessions.notify_changed()
        return changed

    def _restore_value(self, value: LayerMapping | None) -> bool:
        """Restore one retained value and publish its new cursor state."""
        if value is None:
            return False
        changed = self._restore(value)
        self._sessions.notify_changed()
        return changed

    def _close(self) -> None:
        """Release the exact coordinator claim and all retained mappings."""
        self._session_id = None
        self._history = None
        self._gesture_active = False
        self._sessions.release(self)


__all__ = ["TransformProvisionalSession"]
