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
"""Detachable view-session state for one mounted canvas document."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum

from qpane.sdk.inspection import InspectionStateStore
from qpane.sdk.layout import ResponsiveGridPolicy
from qpane.sdk.types import ComparisonOrientation, LinkedGroup


@dataclass(frozen=True, slots=True)
class CanvasInspectionGroup:
    """Describe host-owned linked inspection members without exposing QPane."""

    group_id: uuid.UUID
    members: tuple[uuid.UUID, ...]

    def __post_init__(self) -> None:
        """Reject empty or duplicate membership before mutating inspection state."""
        if not self.members:
            raise ValueError("inspection group must contain at least one member")
        if len(set(self.members)) != len(self.members):
            raise ValueError("inspection group members must be unique")


class CanvasPresentationKind(str, Enum):
    """Name the built-in arrangement used by one canvas view session."""

    SINGLE = "single"
    TABBED = "tabbed"
    GRID = "grid"
    COMPARISON = "comparison"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class CanvasComparison:
    """Describe transient comparison state between two composition targets."""

    primary_id: uuid.UUID
    secondary_id: uuid.UUID
    split_position: float = 0.5
    orientation: ComparisonOrientation = ComparisonOrientation.VERTICAL

    def __post_init__(self) -> None:
        """Validate identities and normalize the divider position."""
        if self.primary_id == self.secondary_id:
            raise ValueError("comparison targets must be different")
        if not 0.0 <= float(self.split_position) <= 1.0:
            raise ValueError("split_position must be between zero and one")


@dataclass(frozen=True, slots=True)
class CanvasPresentation:
    """Describe which document compositions a session presents and how."""

    kind: CanvasPresentationKind = CanvasPresentationKind.SINGLE
    target_ids: tuple[uuid.UUID, ...] = ()
    comparison: CanvasComparison | None = None
    provider_id: str | None = None
    grid_policy: ResponsiveGridPolicy | None = None

    def __post_init__(self) -> None:
        """Reject duplicate targets and inconsistent comparison payloads."""
        if len(set(self.target_ids)) != len(self.target_ids):
            raise ValueError("presentation target IDs must be unique")
        if self.kind is CanvasPresentationKind.COMPARISON:
            if self.comparison is None:
                raise ValueError("comparison presentation requires comparison state")
            expected = {
                self.comparison.primary_id,
                self.comparison.secondary_id,
            }
            if set(self.target_ids) != expected:
                raise ValueError("comparison targets must match target_ids")
        elif self.comparison is not None:
            raise ValueError("comparison state requires a comparison presentation")
        if self.kind is CanvasPresentationKind.CUSTOM:
            if self.provider_id is None or not self.provider_id.strip():
                raise ValueError("custom presentation requires a provider_id")
        elif self.provider_id is not None:
            raise ValueError("provider_id requires a custom presentation")
        if (
            self.grid_policy is not None
            and self.kind is not CanvasPresentationKind.GRID
        ):
            raise ValueError("grid_policy requires a grid presentation")


@dataclass(frozen=True, slots=True)
class CanvasSessionSnapshot:
    """Return detached state for one view session."""

    active_composition_id: uuid.UUID | None
    presentation: CanvasPresentation
    revision: int


class CanvasViewSession:
    """Own activation and presentation state independently of document content."""

    def __init__(
        self,
        *,
        inspection: InspectionStateStore | None = None,
    ) -> None:
        """Create an independent session, optionally sharing inspection state."""
        self._session_id = uuid.uuid4()
        self._active_composition_id: uuid.UUID | None = None
        self._presentation = CanvasPresentation()
        self._inspection = inspection or InspectionStateStore()
        self._revision = 0
        self._subscribers: list[Callable[[CanvasSessionSnapshot], None]] = []

    @property
    def session_id(self) -> uuid.UUID:
        """Return this view session's stable runtime identity."""
        return self._session_id

    @property
    def active_composition_id(self) -> uuid.UUID | None:
        """Return the composition currently receiving focused interaction."""
        return self._active_composition_id

    @property
    def presentation(self) -> CanvasPresentation:
        """Return the immutable current presentation."""
        return self._presentation

    @property
    def inspection(self) -> InspectionStateStore:
        """Return this session's explicit normalized-inspection owner."""
        return self._inspection

    def setInspectionGroups(self, groups: Iterable[CanvasInspectionGroup]) -> None:
        """Replace host-owned linked inspection groups without changing presentation."""
        self._inspection.replace_groups(
            LinkedGroup(group.group_id, group.members) for group in groups
        )

    @property
    def revision(self) -> int:
        """Return the monotonic session-state revision."""
        return self._revision

    def activate(
        self,
        composition_id: uuid.UUID,
        *,
        available_ids: tuple[uuid.UUID, ...],
    ) -> bool:
        """Activate one available composition without mutating document content."""
        if not isinstance(composition_id, uuid.UUID):
            raise TypeError("composition_id must be a UUID")
        if composition_id not in available_ids:
            raise KeyError("composition_id does not exist")
        if self._active_composition_id == composition_id:
            return False
        self._active_composition_id = composition_id
        if self._presentation.kind is CanvasPresentationKind.SINGLE:
            self._presentation = CanvasPresentation(
                CanvasPresentationKind.SINGLE,
                (composition_id,),
            )
        self._publish()
        return True

    def clear_activation(self) -> bool:
        """Clear focused activation without removing any document content."""
        if self._active_composition_id is None:
            return False
        self._active_composition_id = None
        self._publish()
        return True

    def set_presentation(
        self,
        presentation: CanvasPresentation,
        *,
        available_ids: tuple[uuid.UUID, ...],
    ) -> bool:
        """Install a presentation whose targets all exist in the document."""
        if not isinstance(presentation, CanvasPresentation):
            raise TypeError("presentation must be a CanvasPresentation")
        missing = set(presentation.target_ids).difference(available_ids)
        if missing:
            raise KeyError("presentation contains unavailable composition targets")
        if presentation == self._presentation:
            return False
        self._presentation = presentation
        if (
            self._active_composition_id not in presentation.target_ids
            and presentation.target_ids
        ):
            self._active_composition_id = presentation.target_ids[0]
        self._publish()
        return True

    def reconcile(self, available_ids: tuple[uuid.UUID, ...]) -> bool:
        """Remove unavailable targets and select a deterministic successor."""
        available = set(available_ids)
        targets = tuple(
            target_id
            for target_id in self._presentation.target_ids
            if target_id in available
        )
        active = self._active_composition_id
        if active not in available:
            active = (
                targets[0] if targets else (available_ids[0] if available_ids else None)
            )
        if self._presentation.kind is CanvasPresentationKind.COMPARISON:
            comparison = self._presentation.comparison
            if (
                comparison is None
                or comparison.primary_id not in available
                or comparison.secondary_id not in available
            ):
                presentation = CanvasPresentation(
                    CanvasPresentationKind.SINGLE,
                    () if active is None else (active,),
                )
            else:
                presentation = self._presentation
        else:
            presentation = CanvasPresentation(
                self._presentation.kind,
                targets,
                provider_id=self._presentation.provider_id,
                grid_policy=self._presentation.grid_policy,
            )
        if active == self._active_composition_id and presentation == self._presentation:
            return False
        self._active_composition_id = active
        self._presentation = presentation
        self._publish()
        return True

    def snapshot(self) -> CanvasSessionSnapshot:
        """Return detached immutable session state."""
        return CanvasSessionSnapshot(
            self._active_composition_id,
            self._presentation,
            self._revision,
        )

    def subscribe(
        self,
        callback: Callable[[CanvasSessionSnapshot], None],
    ) -> Callable[[], None]:
        """Observe session changes and return an idempotent unsubscribe function."""
        if callback not in self._subscribers:
            self._subscribers.append(callback)

        def unsubscribe() -> None:
            """Detach the session observer when it remains registered."""
            if callback in self._subscribers:
                self._subscribers.remove(callback)

        return unsubscribe

    def _publish(self) -> None:
        """Advance revision and publish one detached snapshot."""
        self._revision += 1
        snapshot = self.snapshot()
        for callback in tuple(self._subscribers):
            callback(snapshot)
