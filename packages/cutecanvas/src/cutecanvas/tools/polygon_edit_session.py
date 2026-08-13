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
"""Own bounded topology history for unfinished polygon coverage."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from cutecanvas.edit_sessions import EditSessionKind
from cutecanvas.editor.provisional_history import (
    BoundedProvisionalHistory,
    ProvisionalHistorySnapshot,
)
from cutecanvas.editor.session_coordination import EditSessionCoordinator
from PySide6.QtCore import QPointF

from .polygon_coverage_session import PolygonCoverageSession, PolygonCoverageVertex

PolygonTopology = tuple[PolygonCoverageVertex, ...]


class PolygonCoverageEditSession:
    """Retain semantic polygon checkpoints until publish or cancellation."""

    def __init__(
        self,
        *,
        sessions: EditSessionCoordinator,
        kind: EditSessionKind,
        tool_mode: str,
        publish: Callable[[tuple[QPointF, ...]], bool],
        changed: Callable[[], None],
        closed: Callable[[], None],
    ) -> None:
        """Claim the shared coordinator around one empty polygon base."""
        self._sessions = sessions
        self._kind = kind
        self._tool_mode = tool_mode
        self._publish = publish
        self._changed = changed
        self._closed = closed
        self._session_id: uuid.UUID | None = uuid.uuid4()
        self._topology = PolygonCoverageSession()
        self._history = BoundedProvisionalHistory[PolygonTopology](
            (), checkpoint_limit=sessions.policy.checkpoint_limit
        )
        self._gesture_active = False

    @classmethod
    def begin(
        cls,
        *,
        sessions: EditSessionCoordinator,
        kind: EditSessionKind,
        tool_mode: str,
        publish: Callable[[tuple[QPointF, ...]], bool],
        changed: Callable[[], None],
        closed: Callable[[], None],
    ) -> PolygonCoverageEditSession | None:
        """Create and claim one polygon session or reject competing ownership."""
        owner = cls(
            sessions=sessions,
            kind=kind,
            tool_mode=tool_mode,
            publish=publish,
            changed=changed,
            closed=closed,
        )
        return owner if sessions.claim(owner) else None

    @property
    def topology(self) -> PolygonCoverageSession:
        """Return the mutable topology owner used by direct pointer input."""
        return self._topology

    @property
    def session_id(self) -> uuid.UUID | None:
        """Return the unresolved polygon session identity."""
        return self._session_id

    @property
    def session_kind(self) -> EditSessionKind:
        """Return whether this polygon authors selection or mask coverage."""
        return self._kind

    @property
    def session_tool_mode(self) -> str:
        """Return the registered polygon tool mode."""
        return self._tool_mode

    @property
    def gesture_active(self) -> bool:
        """Return whether a vertex press remains unresolved."""
        return self._gesture_active

    @property
    def can_apply(self) -> bool:
        """Return whether a settled valid polygon can be published."""
        return (
            self._session_id is not None
            and not self._gesture_active
            and self._topology.can_finish
        )

    @property
    def can_cancel(self) -> bool:
        """Return whether the unfinished polygon can be discarded."""
        return self._session_id is not None

    @property
    def provisional_history(self) -> ProvisionalHistorySnapshot | None:
        """Return the bounded topology cursor while unresolved."""
        return None if self._session_id is None else self._history.snapshot

    def begin_gesture(self) -> None:
        """Mark direct vertex input active without retaining partial movement."""
        self._gesture_active = True
        self._sessions.notify_changed()

    def settle(self, label: str) -> bool:
        """Retain the completed topology operation as one checkpoint."""
        self._gesture_active = False
        retained = self._history.push(self._topology.vertices, label)
        self._sessions.notify_changed()
        return retained

    def undo_provisional(self) -> bool:
        """Restore the previous retained topology."""
        return self._restore(self._history.undo())

    def redo_provisional(self) -> bool:
        """Restore the next retained topology."""
        return self._restore(self._history.redo())

    def apply(self) -> bool:
        """Publish valid polygon coverage as one durable document edit."""
        if not self.can_apply:
            return False
        if not self._publish(self._topology.points):
            return False
        self._close()
        return True

    def cancel(self) -> bool:
        """Discard the unfinished polygon and release its history."""
        if self._session_id is None:
            return False
        self._close()
        return True

    def suspend(self) -> bool:
        """Release pointer ownership while retaining authored topology."""
        if self._session_id is None:
            return False
        changed = self._gesture_active
        self._gesture_active = False
        self._sessions.notify_changed()
        return changed

    def _restore(self, vertices: PolygonTopology | None) -> bool:
        """Restore one retained topology and publish feedback state."""
        if vertices is None:
            return False
        changed = self._topology.restore(vertices)
        if changed:
            self._changed()
        self._sessions.notify_changed()
        return changed

    def _close(self) -> None:
        """Release all topology state after the coordinator claim."""
        self._session_id = None
        self._gesture_active = False
        self._closed()
        self._sessions.release(self)


__all__ = ["PolygonCoverageEditSession", "PolygonTopology"]
