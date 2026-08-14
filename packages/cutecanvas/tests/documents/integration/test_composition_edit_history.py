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
"""Tests for authoritative chronological composition edit history."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from PySide6.QtCore import QRectF

from cutecanvas import CanvasDocument, ExternalHistoryPolicy
from cutecanvas.composition.edit_controller import CompositionEditController
from cutecanvas.composition.edit_history import CompositionEditHistory
from cutecanvas.composition.history_model import (
    HistoryDurability,
    HistoryTruncationReason,
)
from cutecanvas.composition.resource_lifetime import (
    CompositionResourceLifetime,
    ResourceLeaseKind,
)
from cutecanvas.resources import ProjectResourceReference
from cutecanvas.scene.mapping_edit import LayerMappingEdit, LayerMappingTransition
from qpane.scene.affine import LayerTransform
from qpane.scene.projective import ProjectiveLayerTransform

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


@dataclass(frozen=True, slots=True)
class _TransientCommand:
    """Representative non-durable selection-state transition."""

    scope_id: uuid.UUID
    label: str
    retained_bytes: int
    history_durability: HistoryDurability = HistoryDurability.TRANSIENT


def _placement_edit(scope_id: uuid.UUID, x: float) -> LayerMappingEdit:
    """Return a representative transform edit in ``scope_id``."""
    return LayerMappingEdit(
        scene_id=scope_id,
        transitions=(
            LayerMappingTransition(
                layer_id=uuid.uuid4(),
                before=_TRANSFORM,
                after=LayerTransform(dx=x),
            ),
        ),
    )


def test_mapping_edit_budget_accounts_for_projective_coefficients() -> None:
    """History budgeting must include all retained homography coefficients."""
    edit = LayerMappingEdit(
        scene_id=uuid.uuid4(),
        transitions=(
            LayerMappingTransition(
                layer_id=uuid.uuid4(),
                before=LayerTransform(),
                after=ProjectiveLayerTransform(m13=0.001),
            ),
        ),
    )

    assert edit.retained_bytes == 120


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


def test_durable_commit_is_current_and_identity_replayable_under_all_soft_limits() -> (
    None
):
    """Every accepted durable command must survive enforcement as current undo."""
    for command_limit in (0, 1, 3):
        for byte_limit in (0, 1, 8):
            for retained_bytes in (0, 1, 16):
                scope_id = uuid.uuid4()
                history = CompositionEditHistory(
                    command_limit=command_limit,
                    byte_limit=byte_limit,
                )
                controller = CompositionEditController(history)
                controller.register_handler(
                    _TestCommand,
                    undo=lambda _command: True,
                    redo=lambda _command: True,
                )
                for index in range(5):
                    command = _TestCommand(
                        scope_id,
                        f"edit-{index}",
                        retained_bytes,
                    )
                    commit = controller.record_applied(command)
                    candidate = history.undo_entry(scope_id)
                    assert candidate is not None
                    assert candidate.metadata.command_id == commit.metadata.command_id
                    assert candidate.command is command
                    assert controller.undo_identity(
                        scope_id,
                        commit.metadata.command_id,
                    ).changed
                    assert history.redo_entry(scope_id) is candidate
                    assert controller.redo_identity(
                        scope_id,
                        commit.metadata.command_id,
                    ).changed
                    assert history.undo_entry(scope_id) is candidate


def test_policy_truncation_reports_exact_identity_and_reason() -> None:
    """Policy eviction must publish all removed identities with one typed reason."""
    scope_id = uuid.uuid4()
    truncations = []
    history = CompositionEditHistory(
        command_limit=1,
        byte_limit=1024,
        truncated=truncations.append,
    )
    first = history.record_applied(_TestCommand(scope_id, "first", 1))
    second = history.record_applied(_TestCommand(scope_id, "second", 1))

    assert second.metadata.sequence_number > first.metadata.sequence_number
    assert len(truncations) == 1
    assert truncations[0].reason is HistoryTruncationReason.COMMAND_LIMIT
    assert tuple(item.command_id for item in truncations[0].evicted) == (
        first.metadata.command_id,
    )


def test_transient_pressure_does_not_consume_durable_retention_budget() -> None:
    """Selection-like churn must not evict the newest durable edit guarantee."""
    scope_id = uuid.uuid4()
    history = CompositionEditHistory(command_limit=1, byte_limit=1)
    durable_commit = history.record_applied(_TestCommand(scope_id, "delete", 128))

    for index in range(20):
        history.record_applied(_TransientCommand(scope_id, f"selection-{index}", 128))

    retained_ids = {
        entry.metadata.command_id for entry in history.undo_entries(scope_id)
    }
    assert durable_commit.metadata.command_id in retained_ids


def test_canvas_document_external_history_observes_and_replays_exact_identity() -> None:
    """External policy mode must expose safe replay without private limits."""
    commits = []
    document = CanvasDocument(
        history_policy=ExternalHistoryPolicy(),
        history_committed=commits.append,
    )
    scope_id = document.create_composition(QRectF(0.0, 0.0, 32.0, 32.0))
    controller = document.resources.compositions.edit_controller
    controller.register_handler(
        _TestCommand,
        undo=lambda _command: True,
        redo=lambda _command: True,
    )
    for index in range(150):
        controller.record_applied(_TestCommand(scope_id, f"edit-{index}", 1 << 20))

    candidate = document.history.undo_candidate(scope_id)
    assert candidate is not None
    assert len(commits) == 150
    assert len(document.history.undo_entries(scope_id)) == 150
    assert not document.history.undo(scope_id, uuid.uuid4())
    assert document.history.undo(scope_id, candidate.command_id)
    assert not document.history.redo(scope_id, uuid.uuid4())
    assert document.history.redo(scope_id, candidate.command_id)
