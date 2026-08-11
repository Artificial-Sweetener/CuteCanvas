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
"""Coordinate the single unresolved edit session and host history routing."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Protocol

from cutecanvas.edit_sessions import (
    EditSessionKind,
    EditSessionPolicy,
    EditSessionSnapshot,
    EditSessionToolChange,
    EditSessionUndoBoundary,
)

from .provisional_history import ProvisionalHistorySnapshot


class ProvisionalEditSession(Protocol):
    """Contract implemented by one authoritative in-progress edit owner."""

    @property
    def session_id(self) -> uuid.UUID | None:
        """Return the active session identity, if unresolved."""
        ...

    @property
    def session_kind(self) -> EditSessionKind:
        """Return the public semantic session kind."""
        ...

    @property
    def session_tool_mode(self) -> str:
        """Return the public tool mode that opened the session."""
        ...

    @property
    def gesture_active(self) -> bool:
        """Return whether a direct pointer sequence is unresolved."""
        ...

    @property
    def can_apply(self) -> bool:
        """Return whether the current provisional result can be applied."""
        ...

    @property
    def can_cancel(self) -> bool:
        """Return whether the unresolved session can be cancelled."""
        ...

    @property
    def provisional_history(self) -> ProvisionalHistorySnapshot | None:
        """Return bounded history state while the session is active."""
        ...

    def undo_provisional(self) -> bool:
        """Restore the previous provisional checkpoint."""
        ...

    def redo_provisional(self) -> bool:
        """Restore the next provisional checkpoint."""
        ...

    def apply(self) -> bool:
        """Commit the latest provisional state and close the session."""
        ...

    def cancel(self) -> bool:
        """Restore the immutable base and close the session."""
        ...

    def suspend(self) -> bool:
        """Release pointer ownership without resolving the session."""
        ...


class EditSessionCoordinator:
    """Own exclusivity, detached state, policy, and unified Undo routing."""

    def __init__(
        self,
        *,
        changed: Callable[[EditSessionSnapshot | None], None],
        policy: EditSessionPolicy | None = None,
    ) -> None:
        """Create an empty coordinator with safe session-confined defaults."""
        self._changed = changed
        self._policy = policy or EditSessionPolicy()
        self._active: ProvisionalEditSession | None = None

    @property
    def policy(self) -> EditSessionPolicy:
        """Return the current host-selected routing policy."""
        return self._policy

    @property
    def active(self) -> bool:
        """Return whether one unresolved session owns editor history routing."""
        return self.snapshot is not None

    @property
    def snapshot(self) -> EditSessionSnapshot | None:
        """Return detached state for the active valid session."""
        owner = self._active
        if owner is None or owner.session_id is None:
            return None
        history = owner.provisional_history
        if history is None:
            return None
        return EditSessionSnapshot(
            session_id=owner.session_id,
            kind=owner.session_kind,
            tool_mode=owner.session_tool_mode,
            gesture_active=owner.gesture_active,
            can_apply=owner.can_apply,
            can_cancel=owner.can_cancel,
            can_undo=history.can_undo and not owner.gesture_active,
            can_redo=history.can_redo and not owner.gesture_active,
            undo_label=(None if owner.gesture_active else history.undo_label),
            redo_label=(None if owner.gesture_active else history.redo_label),
            undo_depth=history.undo_depth,
            redo_depth=history.redo_depth,
        )

    def set_policy(self, policy: EditSessionPolicy) -> bool:
        """Replace host routing policy without resizing an active history."""
        normalized = EditSessionPolicy(
            checkpoint_limit=policy.checkpoint_limit,
            undo_boundary=policy.undo_boundary,
            tool_change=policy.tool_change,
        )
        if self.active and normalized.checkpoint_limit != self._policy.checkpoint_limit:
            return False
        if normalized == self._policy:
            return True
        self._policy = normalized
        self.notify_changed()
        return True

    def claim(self, owner: ProvisionalEditSession) -> bool:
        """Grant exclusive session ownership according to tool-change policy."""
        if self._active is owner:
            return True
        if self._active is not None:
            resolution = self._policy.tool_change
            if resolution is EditSessionToolChange.REQUIRE_RESOLUTION:
                return False
            if resolution is EditSessionToolChange.APPLY:
                self._active.apply()
            else:
                self._active.cancel()
            if self._active is not None:
                return False
        self._active = owner
        self.notify_changed()
        return True

    def prepare_tool_change(self, mode: str) -> bool:
        """Resolve or reject a persistent change away from the session tool."""
        owner = self._active
        if owner is None or owner.session_tool_mode == mode:
            return True
        resolution = self._policy.tool_change
        if resolution is EditSessionToolChange.REQUIRE_RESOLUTION:
            return False
        if resolution is EditSessionToolChange.APPLY:
            owner.apply()
        else:
            owner.cancel()
        return self._active is None

    def release(self, owner: ProvisionalEditSession) -> bool:
        """Release the exact active owner without disturbing a replacement."""
        if self._active is not owner:
            return False
        self._active = None
        self._changed(None)
        return True

    def notify_changed(self) -> None:
        """Publish the latest detached session state."""
        self._changed(self.snapshot)

    def undo(self, document_undo: Callable[[], bool]) -> bool:
        """Route Undo to provisional history or the durable document."""
        owner = self._active
        snapshot = self.snapshot
        if owner is None or snapshot is None:
            return document_undo()
        if snapshot.gesture_active:
            return False
        if snapshot.can_undo:
            return owner.undo_provisional()
        if self._policy.undo_boundary is EditSessionUndoBoundary.CANCEL_SESSION:
            return owner.cancel()
        return False

    def redo(self, document_redo: Callable[[], bool]) -> bool:
        """Route Redo without crossing an unresolved session boundary."""
        owner = self._active
        snapshot = self.snapshot
        if owner is None or snapshot is None:
            return document_redo()
        if snapshot.gesture_active:
            return False
        return snapshot.can_redo and owner.redo_provisional()

    def apply(self) -> bool:
        """Apply the active session when present."""
        return self._active is not None and self._active.apply()

    def cancel(self) -> bool:
        """Cancel the active session when present."""
        return self._active is not None and self._active.cancel()

    def suspend(self) -> bool:
        """Suspend direct input without resolving provisional history."""
        return self._active is not None and self._active.suspend()


__all__ = ["EditSessionCoordinator", "ProvisionalEditSession"]
