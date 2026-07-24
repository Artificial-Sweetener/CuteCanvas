#    QPane + CuteCanvas - High-performance PySide6 rendering and editing
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
"""Tests for authoritative chronological composition edit history."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from cutecanvas.composition.edit_controller import CompositionEditController
from cutecanvas.composition.edit_history import CompositionEditHistory
from cutecanvas.composition.resource_lifetime import (
    CompositionResourceLifetime,
    ResourceLeaseKind,
)
from cutecanvas.resources import ProjectResourceReference
from cutecanvas.scene.transform_edit import LayerTransformEdit
from qpane.scene.affine import LayerTransform

_TRANSFORM = LayerTransform()


@dataclass(frozen=True, slots=True)
class _TestCommand:
    """Small generic command used to verify dispatch behavior."""

    scope_id: uuid.UUID
    label: str
    retained_bytes: int


@dataclass(frozen=True, slots=True)
class _ResourceCommand:
    """History command retaining one reusable source payload."""

    scope_id: uuid.UUID
    retained_bytes: int
    retained_resources: tuple[ProjectResourceReference, ...]


def _placement_edit(scope_id: uuid.UUID, x: float) -> LayerTransformEdit:
    """Return a representative transform edit in ``scope_id``."""
    return LayerTransformEdit(
        scene_id=scope_id,
        layer_id=uuid.uuid4(),
        before=_TRANSFORM,
        after=LayerTransform(dx=x),
    )


def test_edit_history_advances_each_scope_independently() -> None:
    """Undo and redo branches must remain composition scoped."""
    history = CompositionEditHistory()
    first_scope = uuid.uuid4()
    second_scope = uuid.uuid4()
    first = _placement_edit(first_scope, 10.0)
    second = _placement_edit(second_scope, 20.0)

    history.record_applied(first)
    history.record_applied(second)
    assert history.commit_undo(first)

    assert history.undo_candidate(first_scope) is None
    assert history.redo_candidate(first_scope) is first
    assert history.undo_candidate(second_scope) is second
    assert history.redo_candidate(second_scope) is None


def test_edit_history_evicts_oldest_commands_by_byte_budget() -> None:
    """Large raster patches must displace old history without parallel limits."""
    scope_id = uuid.uuid4()
    history = CompositionEditHistory(command_limit=10, byte_limit=96)
    first = _placement_edit(scope_id, 10.0)
    second = _placement_edit(scope_id, 20.0)

    history.record_applied(first)
    history.record_applied(second)

    assert history.undo_candidate(scope_id) is second
    assert history.retained_bytes(scope_id) == 96
    assert not history.commit_undo(first)


def test_recording_an_edit_discards_only_its_scope_redo_branch() -> None:
    """A new edit should branch chronologically without touching other scopes."""
    first_scope = uuid.uuid4()
    second_scope = uuid.uuid4()
    history = CompositionEditHistory()
    first = _placement_edit(first_scope, 10.0)
    second = _placement_edit(second_scope, 20.0)
    history.record_applied(first)
    history.record_applied(second)
    assert history.commit_undo(first)
    assert history.commit_undo(second)

    replacement = _placement_edit(first_scope, 30.0)
    history.record_applied(replacement)

    assert history.redo_candidate(first_scope) is None
    assert history.redo_candidate(second_scope) is second


def test_controller_dispatches_one_chronological_timeline_by_command_type() -> None:
    """Different domains must execute from the same ordered scope history."""
    scope_id = uuid.uuid4()
    history = CompositionEditHistory()
    controller = CompositionEditController(history)
    observed: list[str] = []

    def undo(command) -> bool:
        """Capture generic undo dispatch."""
        observed.append(f"undo:{command.label}")
        return True

    def redo(command) -> bool:
        """Capture generic redo dispatch."""
        observed.append(f"redo:{command.label}")
        return True

    controller.register_handler(_TestCommand, undo=undo, redo=redo)
    controller.record_applied(_TestCommand(scope_id, "first", 1))
    controller.record_applied(_TestCommand(scope_id, "second", 1))

    assert controller.undo(scope_id).changed
    assert controller.undo(scope_id).changed
    assert controller.redo(scope_id).changed
    assert observed == ["undo:second", "undo:first", "redo:first"]


def test_controller_notifies_scope_after_record_undo_and_redo() -> None:
    """History presentation must observe every successful chronology change."""
    scope_id = uuid.uuid4()
    observed: list[uuid.UUID] = []
    controller = CompositionEditController(
        CompositionEditHistory(),
        changed=observed.append,
    )
    controller.register_handler(
        _TestCommand,
        undo=lambda _command: True,
        redo=lambda _command: True,
    )
    controller.record_applied(_TestCommand(scope_id, "stroke", 1))
    assert controller.undo(scope_id).changed
    assert controller.redo(scope_id).changed

    assert observed == [scope_id, scope_id, scope_id]


def test_history_releases_resource_leases_on_branch_discard_and_eviction() -> None:
    """Chronology must expose source reachability until a command is discarded."""
    lifetime = CompositionResourceLifetime()
    released: list[_ResourceCommand] = []
    history = CompositionEditHistory(
        command_limit=1,
        resource_lifetime=lifetime,
        released=released.append,
    )
    scope_id = uuid.uuid4()
    first_source = ProjectResourceReference(uuid.uuid4())
    second_source = ProjectResourceReference(uuid.uuid4())
    first = _ResourceCommand(scope_id, 1, (first_source,))
    second = _ResourceCommand(scope_id, 1, (second_source,))

    history.record_applied(first)
    assert lifetime.lease_count(first_source, ResourceLeaseKind.HISTORY) == 1
    history.record_applied(second)

    assert lifetime.total_leases(first_source) == 0
    assert lifetime.lease_count(second_source, ResourceLeaseKind.HISTORY) == 1
    assert released == [first]
    history.clear_scope(scope_id)
    assert lifetime.total_leases(second_source) == 0
    assert released == [first, second]
