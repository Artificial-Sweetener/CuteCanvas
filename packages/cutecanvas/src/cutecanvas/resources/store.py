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
"""Authoritative identity, revision, and dependency graph for project resources."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import replace

from .model import (
    ProjectResourceKind,
    ProjectResourceRecord,
    ProjectResourceReference,
)


class ProjectResourceStore:
    """Own every CuteCanvas resource record and its dependency invalidation."""

    def __init__(
        self,
        *,
        changed: Callable[[ProjectResourceRecord], None] | None = None,
    ) -> None:
        """Initialize an empty project resource graph."""
        self._changed = changed
        self._records: dict[uuid.UUID, ProjectResourceRecord] = {}
        self._dependents: dict[uuid.UUID, set[uuid.UUID]] = {}
        self._revision = 0

    @property
    def revision(self) -> int:
        """Return the aggregate graph revision."""
        return self._revision

    def create(
        self,
        kind: ProjectResourceKind,
        *,
        editable: bool,
        resource_id: uuid.UUID | None = None,
        dependencies: Iterable[uuid.UUID] = (),
    ) -> ProjectResourceRecord:
        """Create one resource after validating all dependency identities."""
        resolved_id = resource_id or uuid.uuid4()
        if resolved_id in self._records:
            raise ValueError("project resource ID already exists")
        record = ProjectResourceRecord(
            resolved_id,
            kind,
            editable,
            dependencies=frozenset(dependencies),
        )
        self._validate_dependencies(record.resource_id, record.dependencies)
        self._install(record)
        return record

    def restore(self, record: ProjectResourceRecord) -> None:
        """Restore one persisted record without weakening graph validation."""
        if not isinstance(record, ProjectResourceRecord):
            raise TypeError("record must be a ProjectResourceRecord")
        if record.resource_id in self._records:
            raise ValueError("project resource ID already exists")
        self._validate_dependencies(record.resource_id, record.dependencies)
        self._install(record)

    def get(self, resource_id: uuid.UUID) -> ProjectResourceRecord | None:
        """Return one resource record when retained."""
        return self._records.get(resource_id)

    def resolve(
        self,
        reference: ProjectResourceReference,
    ) -> ProjectResourceRecord | None:
        """Resolve a stable reference through the authoritative resource record."""
        if not isinstance(reference, ProjectResourceReference):
            return None
        return self._records.get(reference.resource_id)

    def records(self) -> tuple[ProjectResourceRecord, ...]:
        """Return a deterministic immutable resource snapshot."""
        return tuple(self._records[item] for item in sorted(self._records, key=str))

    def install(self, records: Iterable[ProjectResourceRecord]) -> None:
        """Atomically create or replace a validated subset of resource records."""
        replacements = self._record_map(records)
        candidate = dict(self._records)
        candidate.update(replacements)
        self._replace_graph(candidate, publish=replacements)

    def restore_state(self, records: Iterable[ProjectResourceRecord]) -> None:
        """Atomically restore one exact complete graph snapshot."""
        replacement = self._record_map(records)
        self._replace_graph(replacement, publish=replacement)

    def set_dependencies(
        self,
        resource_id: uuid.UUID,
        dependencies: Iterable[uuid.UUID],
    ) -> bool:
        """Replace dependencies atomically after rejecting missing nodes and cycles."""
        current = self._require(resource_id)
        normalized = frozenset(dependencies)
        if normalized == current.dependencies:
            return False
        self._validate_dependencies(resource_id, normalized)
        replacement = replace(current, dependencies=normalized)
        self._unindex_dependencies(current)
        self._records[resource_id] = replacement
        self._index_dependencies(replacement)
        self._touch_records(self._dependent_closure(resource_id))
        return True

    def validate_dependencies(
        self,
        resource_id: uuid.UUID,
        dependencies: Iterable[uuid.UUID],
    ) -> None:
        """Validate a proposed dependency set without mutating the graph."""
        self._validate_dependencies(resource_id, frozenset(dependencies))

    def set_editable(self, resource_id: uuid.UUID, editable: bool) -> bool:
        """Replace explicit resource editability and invalidate dependents."""
        if not isinstance(editable, bool):
            raise TypeError("editable must be a bool")
        current = self._require(resource_id)
        if current.editable is editable:
            return False
        self._records[resource_id] = replace(current, editable=editable)
        self._touch_records((resource_id,))
        return True

    def set_kind(
        self,
        resource_id: uuid.UUID,
        kind: ProjectResourceKind,
    ) -> bool:
        """Replace a resource's content kind while retaining stable identity."""
        if not isinstance(kind, ProjectResourceKind):
            raise TypeError("kind must be ProjectResourceKind")
        current = self._require(resource_id)
        if current.kind is kind:
            return False
        self._records[resource_id] = replace(current, kind=kind)
        self._touch_records(self._dependent_closure(resource_id))
        return True

    def touch(self, resource_id: uuid.UUID) -> tuple[uuid.UUID, ...]:
        """Advance a changed resource and every transitive dependent once."""
        self._require(resource_id)
        affected = self._dependent_closure(resource_id)
        self._touch_records(affected)
        return affected

    def dependents(self, resource_id: uuid.UUID) -> tuple[uuid.UUID, ...]:
        """Return direct dependents in deterministic order."""
        self._require(resource_id)
        return tuple(sorted(self._dependents.get(resource_id, ()), key=str))

    def remove(self, resource_id: uuid.UUID) -> bool:
        """Remove one unreferenced resource that has no dependent resources."""
        record = self._records.get(resource_id)
        if record is None:
            return False
        if self._dependents.get(resource_id):
            raise ValueError("cannot remove a resource with dependents")
        self._unindex_dependencies(record)
        self._records.pop(resource_id)
        self._dependents.pop(resource_id, None)
        self._revision += 1
        return True

    def clear(self) -> None:
        """Remove the complete resource graph."""
        if not self._records:
            return
        self._records.clear()
        self._dependents.clear()
        self._revision += 1

    def _install(self, record: ProjectResourceRecord) -> None:
        """Install one already validated resource record."""
        self._records[record.resource_id] = record
        self._index_dependencies(record)
        self._revision += 1
        self._publish(record)

    @staticmethod
    def _record_map(
        records: Iterable[ProjectResourceRecord],
    ) -> dict[uuid.UUID, ProjectResourceRecord]:
        """Normalize records while rejecting duplicate or invalid values."""
        normalized: dict[uuid.UUID, ProjectResourceRecord] = {}
        for record in records:
            if not isinstance(record, ProjectResourceRecord):
                raise TypeError("resource graph entries must be ProjectResourceRecord")
            if record.resource_id in normalized:
                raise ValueError("project resource graph contains duplicate identities")
            normalized[record.resource_id] = record
        return normalized

    def _replace_graph(
        self,
        records: dict[uuid.UUID, ProjectResourceRecord],
        *,
        publish: dict[uuid.UUID, ProjectResourceRecord],
    ) -> None:
        """Validate and atomically install one complete candidate graph."""
        self._validate_graph(records)
        self._records = dict(records)
        self._dependents.clear()
        for record in self._records.values():
            self._index_dependencies(record)
        self._revision += 1
        for resource_id in sorted(publish, key=str):
            self._publish(self._records[resource_id])

    @staticmethod
    def _validate_graph(records: dict[uuid.UUID, ProjectResourceRecord]) -> None:
        """Reject missing dependency identities and cycles in a candidate graph."""
        for record in records.values():
            missing = record.dependencies.difference(records)
            if missing:
                raise KeyError(
                    f"unknown project resource dependency: {next(iter(missing))}"
                )
        visiting: set[uuid.UUID] = set()
        visited: set[uuid.UUID] = set()

        def visit(resource_id: uuid.UUID) -> None:
            """Visit one dependency subtree while detecting back edges."""
            if resource_id in visiting:
                raise ValueError("project resource dependencies must remain acyclic")
            if resource_id in visited:
                return
            visiting.add(resource_id)
            for dependency in records[resource_id].dependencies:
                visit(dependency)
            visiting.remove(resource_id)
            visited.add(resource_id)

        for resource_id in records:
            visit(resource_id)

    def _validate_dependencies(
        self,
        resource_id: uuid.UUID,
        dependencies: frozenset[uuid.UUID],
    ) -> None:
        """Reject missing dependencies and every direct or transitive cycle."""
        if resource_id in dependencies:
            raise ValueError("a resource cannot depend on itself")
        missing = dependencies.difference(self._records)
        if missing:
            raise KeyError(
                f"unknown project resource dependency: {next(iter(missing))}"
            )
        for dependency in dependencies:
            if resource_id in self._dependency_closure(dependency):
                raise ValueError("project resource dependencies must remain acyclic")

    def _dependency_closure(self, resource_id: uuid.UUID) -> frozenset[uuid.UUID]:
        """Return one resource and every transitive dependency."""
        pending = [resource_id]
        seen: set[uuid.UUID] = set()
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            record = self._records.get(current)
            if record is not None:
                pending.extend(record.dependencies)
        return frozenset(seen)

    def _dependent_closure(self, resource_id: uuid.UUID) -> tuple[uuid.UUID, ...]:
        """Return the resource followed by each transitive dependent once."""
        ordered: list[uuid.UUID] = []
        pending = [resource_id]
        seen: set[uuid.UUID] = set()
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            ordered.append(current)
            pending.extend(
                sorted(self._dependents.get(current, ()), key=str, reverse=True)
            )
        return tuple(ordered)

    def _touch_records(self, resource_ids: Iterable[uuid.UUID]) -> None:
        """Advance and publish each affected record exactly once."""
        for resource_id in resource_ids:
            current = self._records[resource_id]
            replacement = replace(current, revision=current.revision + 1)
            self._records[resource_id] = replacement
            self._publish(replacement)
        self._revision += 1

    def _index_dependencies(self, record: ProjectResourceRecord) -> None:
        """Index reverse dependency edges for invalidation."""
        for dependency in record.dependencies:
            self._dependents.setdefault(dependency, set()).add(record.resource_id)

    def _unindex_dependencies(self, record: ProjectResourceRecord) -> None:
        """Remove reverse dependency edges owned by one record."""
        for dependency in record.dependencies:
            dependents = self._dependents.get(dependency)
            if dependents is None:
                continue
            dependents.discard(record.resource_id)
            if not dependents:
                self._dependents.pop(dependency, None)

    def _require(self, resource_id: uuid.UUID) -> ProjectResourceRecord:
        """Return one record or raise for a programmer-invalid identity."""
        try:
            return self._records[resource_id]
        except KeyError as exc:
            raise KeyError(f"unknown project resource: {resource_id}") from exc

    def _publish(self, record: ProjectResourceRecord) -> None:
        """Publish one coherent immutable resource observation."""
        if self._changed is not None:
            self._changed(record)
