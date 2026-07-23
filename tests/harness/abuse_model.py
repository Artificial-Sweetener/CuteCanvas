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

"""Serializable actions and results for deterministic CuteCanvas abuse sessions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, TypeAlias

from PySide6.QtCore import QPoint


class PointerKind(str, Enum):
    """Identify the Qt input path used for a stroke."""

    MOUSE = "mouse"
    TOUCH = "touch"
    PEN = "pen"


@dataclass(frozen=True, slots=True)
class HarnessPoint:
    """Store a JSON-safe widget-space point."""

    x: int
    y: int

    def to_qpoint(self) -> QPoint:
        """Convert this value to Qt coordinates."""
        return QPoint(self.x, self.y)


@dataclass(frozen=True, slots=True)
class StrokeAction:
    """Describe one complete pointer stroke."""

    device: PointerKind
    points: tuple[HarnessPoint, ...]
    mask_index: int = 0
    brush_size: int = 30
    step_delay_ms: int = 0
    pressure: float = 0.75
    kind: str = "stroke"

    def __post_init__(self) -> None:
        """Reject actions that cannot represent a complete stroke."""
        if not self.points:
            raise ValueError("A stroke action requires at least one point")
        if self.brush_size < 1:
            raise ValueError("brush_size must be positive")


@dataclass(frozen=True, slots=True)
class UndoAction:
    """Undo the latest committed stroke on one mask."""

    mask_index: int = 0
    kind: str = "undo"


@dataclass(frozen=True, slots=True)
class RedoAction:
    """Redo the latest undone stroke on one mask."""

    mask_index: int = 0
    kind: str = "redo"


@dataclass(frozen=True, slots=True)
class IdleAction:
    """Drain events and require the mounted composition to remain stable."""

    wait_ms: int = 20
    kind: str = "idle"


@dataclass(frozen=True, slots=True)
class WaitAction:
    """Advance Qt time while requiring semantic mask coverage to persist."""

    wait_ms: int
    kind: str = "wait"


@dataclass(frozen=True, slots=True)
class PenLeaveAction:
    """Send the platform transition indicating that the pen left proximity."""

    kind: str = "pen-leave"


@dataclass(frozen=True, slots=True)
class TouchNavigationAction:
    """Describe second-finger takeover followed by pan and pinch motion."""

    primary_start: HarnessPoint
    secondary_start: HarnessPoint
    primary_end: HarnessPoint
    secondary_end: HarnessPoint
    mask_index: int = 0
    kind: str = "touch-navigation"


@dataclass(frozen=True, slots=True)
class PalmContactAction:
    """Describe touch contact expected to be rejected during pen proximity."""

    point: HarnessPoint
    mask_index: int = 0
    kind: str = "palm-contact"


@dataclass(frozen=True, slots=True)
class PenHoverAction:
    """Move a hover-capable stylus without contact to preview the brush."""

    point: HarnessPoint
    mask_index: int = 0
    brush_size: int = 120
    kind: str = "pen-hover"


@dataclass(frozen=True, slots=True)
class MouseHoverAction:
    """Move a genuine mouse to require restoration of its brush cursor."""

    point: HarnessPoint
    stale_touchscreen_metadata: bool = False
    kind: str = "mouse-hover"


@dataclass(frozen=True, slots=True)
class EditorWorkflowAction:
    """Exercise selections, editable RGBA, bounds, and chronological history."""

    kind: str = "editor-workflow"


AbuseAction: TypeAlias = (
    StrokeAction
    | UndoAction
    | RedoAction
    | IdleAction
    | WaitAction
    | PenLeaveAction
    | TouchNavigationAction
    | PalmContactAction
    | PenHoverAction
    | MouseHoverAction
    | EditorWorkflowAction
)


@dataclass(frozen=True, slots=True)
class AbuseViolation:
    """Describe the first invariant violation in an abuse session."""

    action_index: int
    phase: str
    message: str
    point: HarnessPoint | None = None
    color: tuple[int, int, int, int] | None = None


@dataclass(frozen=True, slots=True)
class AbuseReport:
    """Summarize one deterministic abuse execution."""

    seed: int
    action_count: int
    completed_actions: int
    max_feedback_latency_ms: float
    violation: AbuseViolation | None = None

    @property
    def succeeded(self) -> bool:
        """Return whether every action satisfied its invariants."""
        return self.violation is None

    def to_dict(self) -> dict[str, Any]:
        """Return a machine-readable report."""
        payload = asdict(self)
        payload["succeeded"] = self.succeeded
        return payload


def action_to_dict(action: AbuseAction) -> dict[str, Any]:
    """Serialize one abuse action."""
    payload = asdict(action)
    if isinstance(action, StrokeAction):
        payload["device"] = action.device.value
    return payload


def action_from_dict(payload: dict[str, Any]) -> AbuseAction:
    """Deserialize one abuse action from a trace."""
    kind = str(payload["kind"])
    if kind == "stroke":
        return StrokeAction(
            device=PointerKind(payload["device"]),
            points=tuple(HarnessPoint(**point) for point in payload["points"]),
            mask_index=int(payload.get("mask_index", 0)),
            brush_size=int(payload.get("brush_size", 30)),
            step_delay_ms=int(payload.get("step_delay_ms", 0)),
            pressure=float(payload.get("pressure", 0.75)),
        )
    if kind == "undo":
        return UndoAction(mask_index=int(payload.get("mask_index", 0)))
    if kind == "redo":
        return RedoAction(mask_index=int(payload.get("mask_index", 0)))
    if kind == "idle":
        return IdleAction(wait_ms=int(payload.get("wait_ms", 20)))
    if kind == "wait":
        return WaitAction(wait_ms=int(payload["wait_ms"]))
    if kind == "pen-leave":
        return PenLeaveAction()
    if kind == "touch-navigation":
        return TouchNavigationAction(
            primary_start=HarnessPoint(**payload["primary_start"]),
            secondary_start=HarnessPoint(**payload["secondary_start"]),
            primary_end=HarnessPoint(**payload["primary_end"]),
            secondary_end=HarnessPoint(**payload["secondary_end"]),
            mask_index=int(payload.get("mask_index", 0)),
        )
    if kind == "palm-contact":
        return PalmContactAction(
            point=HarnessPoint(**payload["point"]),
            mask_index=int(payload.get("mask_index", 0)),
        )
    if kind == "pen-hover":
        return PenHoverAction(
            point=HarnessPoint(**payload["point"]),
            mask_index=int(payload.get("mask_index", 0)),
            brush_size=int(payload.get("brush_size", 120)),
        )
    if kind == "mouse-hover":
        return MouseHoverAction(
            point=HarnessPoint(**payload["point"]),
            stale_touchscreen_metadata=bool(
                payload.get("stale_touchscreen_metadata", False)
            ),
        )
    if kind == "editor-workflow":
        return EditorWorkflowAction()
    raise ValueError(f"Unknown abuse action kind: {kind}")
