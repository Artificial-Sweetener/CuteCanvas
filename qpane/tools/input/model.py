#    QPane - High-performance PySide6 image viewer
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

"""Immutable device-neutral pointer samples used by QPane interactions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QPointF, Qt


class PointerDeviceKind(str, Enum):
    """Identify the physical pointer category behind an input sample."""

    MOUSE = "mouse"
    TOUCH = "touch"
    PEN = "pen"
    ERASER = "eraser"
    UNKNOWN = "unknown"


class PointerPhase(str, Enum):
    """Describe the lifecycle transition represented by a pointer sample."""

    BEGIN = "begin"
    UPDATE = "update"
    END = "end"
    CANCEL = "cancel"
    HOVER = "hover"


@dataclass(frozen=True, slots=True)
class PointerSample:
    """Capture one pointer observation without retaining a mutable Qt event."""

    pointer_id: int
    device: PointerDeviceKind
    phase: PointerPhase
    position: QPointF
    global_position: QPointF
    pressure: float
    buttons: Qt.MouseButton
    modifiers: Qt.KeyboardModifier
    timestamp_ms: int

    @property
    def is_contact(self) -> bool:
        """Return whether the sample belongs to an active contact sequence."""
        return self.phase in {
            PointerPhase.BEGIN,
            PointerPhase.UPDATE,
        }
