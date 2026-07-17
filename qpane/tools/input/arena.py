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

"""Deterministic arbitration between touch painting and navigation."""

from __future__ import annotations

from enum import Enum


class TouchGestureKind(str, Enum):
    """Identify the interaction that won the current touch sequence."""

    PENDING = "pending"
    NAVIGATION = "navigation"
    PAINTING = "painting"
    REJECTED = "rejected"


class TouchGestureArena:
    """Resolve a touch sequence once and keep that decision stable."""

    def __init__(self, movement_threshold: float = 6.0) -> None:
        """Initialize an idle arena with a logical-pixel movement threshold."""
        self._movement_threshold = max(0.0, float(movement_threshold))
        self._kind = TouchGestureKind.REJECTED
        self._paint_allowed = False

    @property
    def kind(self) -> TouchGestureKind:
        """Return the current arbitration result."""
        return self._kind

    def begin(self, *, navigation_mode: bool, paint_allowed: bool) -> None:
        """Start arbitration for one new sequence."""
        self._paint_allowed = bool(paint_allowed)
        self._kind = (
            TouchGestureKind.NAVIGATION if navigation_mode else TouchGestureKind.PENDING
        )

    def evaluate(
        self,
        *,
        contact_count: int,
        primary_distance: float,
        ending: bool = False,
    ) -> TouchGestureKind:
        """Resolve pending input from contact count and primary movement."""
        if self._kind is not TouchGestureKind.PENDING:
            return self._kind
        if contact_count >= 2:
            self._kind = TouchGestureKind.NAVIGATION
        elif self._paint_allowed and (
            ending or primary_distance >= self._movement_threshold
        ):
            self._kind = TouchGestureKind.PAINTING
        elif ending:
            self._kind = TouchGestureKind.REJECTED
        return self._kind

    def reset(self) -> None:
        """Return the arena to its idle state."""
        self._kind = TouchGestureKind.REJECTED
        self._paint_allowed = False
