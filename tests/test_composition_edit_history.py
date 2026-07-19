#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Tests for authoritative chronological composition edit history."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from qpane.composition.edit_controller import CompositionEditController
from qpane.composition.edit_history import CompositionEditHistory
from qpane.scene.model import LayerPlacement
from qpane.scene.placement_edit import LayerPlacementEdit

_PLACEMENT = LayerPlacement(0.0, 0.0, 100.0, 80.0)


@dataclass(frozen=True, slots=True)
class _TestCommand:
    """Small generic command used to verify dispatch behavior."""

    scope_id: uuid.UUID
    label: str
    retained_bytes: int


def _placement_edit(scope_id: uuid.UUID, x: float) -> LayerPlacementEdit:
    """Return a representative placement edit in ``scope_id``."""
    return LayerPlacementEdit(
        scene_id=scope_id,
        layer_id=uuid.uuid4(),
        before=_PLACEMENT,
        after=LayerPlacement(x, 0.0, 100.0, 80.0),
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
    history = CompositionEditHistory(command_limit=10, byte_limit=64)
    first = _placement_edit(scope_id, 10.0)
    second = _placement_edit(scope_id, 20.0)

    history.record_applied(first)
    history.record_applied(second)

    assert history.undo_candidate(scope_id) is second
    assert history.retained_bytes(scope_id) == 64
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
