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
"""Single-session exclusivity and durable-history boundary proof."""

from __future__ import annotations

import uuid
from typing import cast

import pytest
from cutecanvas.edit_sessions import (
    EditSessionKind,
    EditSessionPolicy,
    EditSessionToolChange,
    EditSessionUndoBoundary,
)
from cutecanvas.editor.provisional_history import (
    BoundedProvisionalHistory,
    ProvisionalHistorySnapshot,
)
from cutecanvas.editor.session_coordination import EditSessionCoordinator


class _Session:
    """Small semantic owner used to prove coordinator behavior independently."""

    def __init__(self, coordinator: EditSessionCoordinator, mode: str) -> None:
        self._coordinator = coordinator
        self.session_id: uuid.UUID | None = None
        self.session_kind = EditSessionKind.TRANSFORM
        self.session_tool_mode = mode
        self.gesture_active = False
        self._history: BoundedProvisionalHistory[int] | None = None

    @property
    def provisional_history(self) -> ProvisionalHistorySnapshot | None:
        return None if self._history is None else self._history.snapshot

    @property
    def can_apply(self) -> bool:
        return self.session_id is not None and not self.gesture_active

    @property
    def can_cancel(self) -> bool:
        return self.session_id is not None

    def begin(self) -> bool:
        self.session_id = uuid.uuid4()
        self._history = BoundedProvisionalHistory(0, checkpoint_limit=4)
        if self._coordinator.claim(self):
            return True
        self.session_id = None
        self._history = None
        return False

    def push(self, value: int) -> None:
        assert self._history is not None
        self._history.push(value, f"Value {value}")
        self._coordinator.notify_changed()

    def undo_provisional(self) -> bool:
        assert self._history is not None
        changed = self._history.undo() is not None
        self._coordinator.notify_changed()
        return changed

    def redo_provisional(self) -> bool:
        assert self._history is not None
        changed = self._history.redo() is not None
        self._coordinator.notify_changed()
        return changed

    def apply(self) -> bool:
        self.session_id = None
        self._history = None
        self._coordinator.release(self)
        return True

    def cancel(self) -> bool:
        return self.apply()

    def suspend(self) -> bool:
        self.gesture_active = False
        return True


class _NoChangeResolutionSession(_Session):
    """Resolve ownership successfully while reporting no document mutation."""

    def apply(self) -> bool:
        super().apply()
        return False

    def cancel(self) -> bool:
        super().cancel()
        return False


def test_active_session_confines_undo_and_redo_to_provisional_state() -> None:
    """Never invoke durable history while one provisional owner remains active."""
    changes = []
    coordinator = EditSessionCoordinator(changed=changes.append)
    session = _Session(coordinator, "transform")
    document_calls: list[str] = []
    assert session.begin()
    session.push(1)

    assert coordinator.undo(lambda: document_calls.append("undo") or True)
    assert coordinator.redo(lambda: document_calls.append("redo") or True)
    assert document_calls == []
    assert changes[-1] is not None


def test_direct_gesture_blocks_checkpoint_navigation_until_settled() -> None:
    """Never restore a settled checkpoint beneath unresolved pointer input."""
    coordinator = EditSessionCoordinator(changed=lambda _state: None)
    session = _Session(coordinator, "transform")
    document_calls: list[str] = []
    assert session.begin()
    session.push(1)
    session.gesture_active = True
    coordinator.notify_changed()

    assert coordinator.snapshot is not None
    assert not coordinator.snapshot.can_undo
    assert not coordinator.undo(lambda: document_calls.append("undo") or True)
    assert not coordinator.redo(lambda: document_calls.append("redo") or True)
    assert document_calls == []


def test_session_only_boundary_stops_before_document_history() -> None:
    """Keep the immutable base above chronological document edits by default."""
    coordinator = EditSessionCoordinator(changed=lambda _state: None)
    session = _Session(coordinator, "transform")
    assert session.begin()
    assert not coordinator.undo(lambda: True)
    assert coordinator.active


def test_cancel_boundary_resolves_session_before_document_history() -> None:
    """Make the first base-boundary Undo cancel without also touching the document."""
    coordinator = EditSessionCoordinator(
        changed=lambda _state: None,
        policy=EditSessionPolicy(
            undo_boundary=EditSessionUndoBoundary.CANCEL_SESSION,
        ),
    )
    session = _Session(coordinator, "transform")
    document_calls: list[str] = []
    assert session.begin()

    assert coordinator.undo(lambda: document_calls.append("undo") or True)
    assert not coordinator.active
    assert document_calls == []
    assert coordinator.undo(lambda: document_calls.append("undo") or True)
    assert document_calls == ["undo"]


def test_second_session_requires_resolution_by_default() -> None:
    """Reject a parallel provisional authority without disturbing the first."""
    coordinator = EditSessionCoordinator(changed=lambda _state: None)
    first = _Session(coordinator, "transform")
    second = _Session(coordinator, "select-polygon")
    assert first.begin()
    assert not second.begin()
    assert coordinator.snapshot is not None
    assert coordinator.snapshot.tool_mode == "transform"


def test_tool_change_policy_can_apply_the_previous_session() -> None:
    """Resolve the previous owner before granting a replacement session."""
    coordinator = EditSessionCoordinator(
        changed=lambda _state: None,
        policy=EditSessionPolicy(tool_change=EditSessionToolChange.APPLY),
    )
    first = _Session(coordinator, "transform")
    second = _Session(coordinator, "select-polygon")
    assert first.begin()
    assert second.begin()
    assert coordinator.snapshot is not None
    assert coordinator.snapshot.tool_mode == "select-polygon"


def test_tool_change_accepts_resolution_without_a_document_mutation() -> None:
    """Judge tool changes by released ownership rather than mutation results."""
    coordinator = EditSessionCoordinator(
        changed=lambda _state: None,
        policy=EditSessionPolicy(tool_change=EditSessionToolChange.APPLY),
    )
    session = _NoChangeResolutionSession(coordinator, "transform")
    assert session.begin()

    assert coordinator.prepare_tool_change("cursor")
    assert not coordinator.active


def test_active_checkpoint_capacity_cannot_change_mid_session() -> None:
    """Keep one session's established memory bound stable until resolution."""
    coordinator = EditSessionCoordinator(changed=lambda _state: None)
    session = _Session(coordinator, "transform")
    assert session.begin()
    assert not coordinator.set_policy(EditSessionPolicy(checkpoint_limit=32))
    assert coordinator.policy.checkpoint_limit == 256


@pytest.mark.parametrize("limit", (True, 0, 4097, 1.5))
def test_public_policy_rejects_non_integer_or_unbounded_capacity(
    limit: object,
) -> None:
    """Reject host policy values that cannot guarantee bounded retention."""
    with pytest.raises(ValueError, match="checkpoint_limit"):
        EditSessionPolicy(checkpoint_limit=cast(int, limit))
