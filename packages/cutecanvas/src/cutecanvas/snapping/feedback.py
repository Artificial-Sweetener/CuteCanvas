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

"""Transient Smart Guide state shared by snapping interaction owners."""

from __future__ import annotations

from collections.abc import Callable

from .model import SnapGuide


class SnapGuideFeedback:
    """Publish active Smart Guides only when their presentation changes."""

    def __init__(self, changed: Callable[[], None]) -> None:
        """Bind the lightweight overlay invalidation callback."""
        self._changed = changed
        self._guides: tuple[SnapGuide, ...] = ()

    @property
    def guides(self) -> tuple[SnapGuide, ...]:
        """Return the current immutable guide presentation."""
        return self._guides

    def publish(self, guides: tuple[SnapGuide, ...]) -> bool:
        """Replace active guides and notify only when presentation differs."""
        normalized = tuple(guides)
        if normalized == self._guides:
            return False
        self._guides = normalized
        self._changed()
        return True

    def clear(self) -> bool:
        """Remove every active guide."""
        return self.publish(())
