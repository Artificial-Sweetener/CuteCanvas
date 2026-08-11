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
"""Own bounded mapping checkpoints for unresolved shared-edge edits."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from cutecanvas.edit_sessions import EditSessionKind
from cutecanvas.scene.mapping_mutations import LayerMappingValue

from .provisional_history import (
    BoundedProvisionalHistory,
    ProvisionalHistorySnapshot,
)
from .session_coordination import EditSessionCoordinator

SharedEdgeMappings = tuple[LayerMappingValue, ...]


class SharedEdgeProvisionalSession:
    """Retain coupled exact mappings until one atomic apply or cancellation."""

    def __init__(
        self,
        *,
        sessions: EditSessionCoordinator,
        scene_id: uuid.UUID,
        base: SharedEdgeMappings,
        restore: Callable[[SharedEdgeMappings, bool], bool],
        commit: Callable[[uuid.UUID, SharedEdgeMappings], bool],
        closed: Callable[[], None],
    ) -> None:
        """Capture an immutable participant base and claim session ownership."""
        self._sessions = sessions
        self._scene_id = scene_id
        self._restore = restore
        self._commit = commit
        self._closed = closed
        self._session_id: uuid.UUID | None = uuid.uuid4()
        self._history = BoundedProvisionalHistory(
            _canonical(base), checkpoint_limit=sessions.policy.checkpoint_limit
        )
        self._gesture_active = False

    @classmethod
    def begin(
        cls,
        *,
        sessions: EditSessionCoordinator,
        scene_id: uuid.UUID,
        base: SharedEdgeMappings,
        restore: Callable[[SharedEdgeMappings, bool], bool],
        commit: Callable[[uuid.UUID, SharedEdgeMappings], bool],
        closed: Callable[[], None],
    ) -> SharedEdgeProvisionalSession | None:
        """Create and claim a coupled mapping session."""
        owner = cls(
            sessions=sessions,
            scene_id=scene_id,
            base=base,
            restore=restore,
            commit=commit,
            closed=closed,
        )
        return owner if sessions.claim(owner) else None

    @property
    def session_id(self) -> uuid.UUID | None:
        """Return the unresolved shared-edge session identity."""
        return self._session_id

    @property
    def session_kind(self) -> EditSessionKind:
        """Return the public coupled-resize session kind."""
        return EditSessionKind.SHARED_EDGE_RESIZE

    @property
    def session_tool_mode(self) -> str:
        """Return the registered Shared Edge Resize mode."""
        return "shared-edge-resize"

    @property
    def gesture_active(self) -> bool:
        """Return whether one seam handle still owns direct input."""
        return self._gesture_active

    @property
    def can_apply(self) -> bool:
        """Return whether a settled coupled mapping set can be applied."""
        return (
            self._session_id is not None
            and not self._gesture_active
            and self.current != self._history.base
        )

    @property
    def can_cancel(self) -> bool:
        """Return whether the unresolved coupled edit can be cancelled."""
        return self._session_id is not None

    @property
    def provisional_history(self) -> ProvisionalHistorySnapshot | None:
        """Return the bounded mapping cursor while unresolved."""
        return None if self._session_id is None else self._history.snapshot

    @property
    def current(self) -> SharedEdgeMappings:
        """Return the exact latest retained participant mappings."""
        return self._history.current

    @property
    def scene_id(self) -> uuid.UUID:
        """Return the scene revision identity captured by this session."""
        return self._scene_id

    @property
    def layer_ids(self) -> frozenset[uuid.UUID]:
        """Return the fixed participant identity set for this session."""
        return frozenset(value.layer_id for value in self._history.base)

    def begin_gesture(self) -> None:
        """Publish direct seam-handle ownership."""
        self._gesture_active = True
        self._sessions.notify_changed()

    def settle(self, values: SharedEdgeMappings, label: str) -> bool:
        """Retain one completed coupled mapping operation."""
        self._gesture_active = False
        changed = self._history.push(_canonical(values), label)
        self._sessions.notify_changed()
        return changed

    def undo_provisional(self) -> bool:
        """Restore the previous coupled mapping set."""
        return self._restore_cursor(self._history.undo())

    def redo_provisional(self) -> bool:
        """Restore the next coupled mapping set."""
        return self._restore_cursor(self._history.redo())

    def apply(self) -> bool:
        """Commit the latest coupled mappings as one durable history edit."""
        if not self.can_apply or not self._commit(self._scene_id, self.current):
            return False
        self._close()
        return True

    def cancel(self) -> bool:
        """Restore the immutable participant base and close the session."""
        if self._session_id is None:
            return False
        self._restore(self._history.base, True)
        self._close()
        return True

    def suspend(self) -> bool:
        """Release direct input while retaining coupled mapping checkpoints."""
        if self._session_id is None:
            return False
        changed = self._gesture_active
        if changed:
            self._restore(self.current, self.current == self._history.base)
        self._gesture_active = False
        self._sessions.notify_changed()
        return changed

    def _restore_cursor(self, values: SharedEdgeMappings | None) -> bool:
        """Publish a retained mapping checkpoint through the preview owner."""
        if values is None:
            return False
        changed = self._restore(values, values == self._history.base)
        self._sessions.notify_changed()
        return changed

    def _close(self) -> None:
        """Release retained mappings and the exact coordinator claim."""
        self._session_id = None
        self._gesture_active = False
        self._closed()
        self._sessions.release(self)


def _canonical(values: SharedEdgeMappings) -> SharedEdgeMappings:
    """Return identity-ordered unique mappings for deterministic equality."""
    ordered = tuple(sorted(values, key=lambda value: str(value.layer_id)))
    if not ordered or len({value.layer_id for value in ordered}) != len(ordered):
        raise ValueError("shared-edge mappings must be non-empty and unique")
    return ordered


__all__ = ["SharedEdgeMappings", "SharedEdgeProvisionalSession"]
