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

"""Declare host-themeable semantic editor cursor feedback."""

from __future__ import annotations

from enum import Enum
from typing import Protocol

from PySide6.QtGui import QCursor


class EditorCursorIntent(str, Enum):
    """Describe editor interaction meaning independently from cursor artwork."""

    DEFAULT = "default"
    FORBIDDEN = "forbidden"
    PRECISE = "precise"
    PRECISE_ADD = "precise_add"
    PRECISE_SUBTRACT = "precise_subtract"
    SELECTION_TRANSLATE = "selection_translate"


class EditorCursorTheme(Protocol):
    """Resolve optional host artwork for semantic CuteCanvas cursor intents."""

    def resolve_cursor(
        self,
        intent: EditorCursorIntent,
        *,
        device_pixel_ratio: float,
    ) -> QCursor | None:
        """Return one themed cursor or defer to the CuteCanvas default."""


__all__ = ["EditorCursorIntent", "EditorCursorTheme"]
