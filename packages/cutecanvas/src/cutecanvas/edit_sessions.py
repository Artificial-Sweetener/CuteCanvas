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
"""Public contracts for bounded in-progress editor sessions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum


class EditSessionKind(str, Enum):
    """Identify the authoritative behavior owned by an edit session."""

    TRANSFORM = "transform"
    POLYGON_SELECTION = "polygon-selection"
    POLYGON_MASK = "polygon-mask"
    SHARED_EDGE_RESIZE = "shared-edge-resize"


class EditSessionHistory(str, Enum):
    """Describe whether a tool creates bounded provisional checkpoints."""

    NONE = "none"
    BOUNDED = "bounded"


class EditSessionUndoBoundary(str, Enum):
    """Control Undo behavior at an active session's immutable base."""

    SESSION_ONLY = "session-only"
    CANCEL_SESSION = "cancel-session"


class EditSessionToolChange(str, Enum):
    """Control persistent tool changes while an edit remains unresolved."""

    REQUIRE_RESOLUTION = "require-resolution"
    APPLY = "apply"
    CANCEL = "cancel"


@dataclass(frozen=True, slots=True)
class ToolEditSessionDeclaration:
    """Declare one tool's in-progress edit-session behavior."""

    kind: EditSessionKind
    history: EditSessionHistory = EditSessionHistory.BOUNDED

    def __post_init__(self) -> None:
        """Normalize supported string enum values at the public boundary."""
        object.__setattr__(self, "kind", EditSessionKind(self.kind))
        object.__setattr__(self, "history", EditSessionHistory(self.history))


@dataclass(frozen=True, slots=True)
class EditorToolDescriptor:
    """Describe one registered editor tool without constructing it."""

    mode: str
    edit_session: ToolEditSessionDeclaration | None = None

    def __post_init__(self) -> None:
        """Reject descriptors that cannot identify a registered tool."""
        if not isinstance(self.mode, str) or not self.mode.strip():
            raise ValueError("mode must be a non-empty string")


@dataclass(frozen=True, slots=True)
class EditSessionPolicy:
    """Configure bounded history routing and persistent tool changes."""

    checkpoint_limit: int = 256
    undo_boundary: EditSessionUndoBoundary = EditSessionUndoBoundary.SESSION_ONLY
    tool_change: EditSessionToolChange = EditSessionToolChange.REQUIRE_RESOLUTION

    def __post_init__(self) -> None:
        """Normalize enum values and reject unsafe checkpoint bounds."""
        if (
            not isinstance(self.checkpoint_limit, int)
            or isinstance(self.checkpoint_limit, bool)
            or not 1 <= self.checkpoint_limit <= 4096
        ):
            raise ValueError("checkpoint_limit must be between 1 and 4096")
        object.__setattr__(
            self,
            "undo_boundary",
            EditSessionUndoBoundary(self.undo_boundary),
        )
        object.__setattr__(
            self,
            "tool_change",
            EditSessionToolChange(self.tool_change),
        )


@dataclass(frozen=True, slots=True)
class EditSessionSnapshot:
    """Report detached state for the one unresolved editor session."""

    session_id: uuid.UUID
    kind: EditSessionKind
    tool_mode: str
    gesture_active: bool
    can_apply: bool
    can_cancel: bool
    can_undo: bool
    can_redo: bool
    undo_label: str | None
    redo_label: str | None
    undo_depth: int
    redo_depth: int


__all__ = [
    "EditSessionHistory",
    "EditSessionKind",
    "EditSessionPolicy",
    "EditSessionSnapshot",
    "EditSessionToolChange",
    "EditSessionUndoBoundary",
    "EditorToolDescriptor",
    "ToolEditSessionDeclaration",
]
