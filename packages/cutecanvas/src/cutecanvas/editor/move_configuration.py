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

"""Authoritative Move-tool configuration state."""

from __future__ import annotations

from collections.abc import Callable

from ..types import MoveToolOptions


class MoveToolConfiguration:
    """Own and publish immutable Move-tool options."""

    def __init__(
        self,
        changed: Callable[[MoveToolOptions], None] | None = None,
    ) -> None:
        """Initialize standard direct-selection behavior."""
        self._options = MoveToolOptions()
        self._changed = changed

    @property
    def options(self) -> MoveToolOptions:
        """Return current immutable options."""
        return self._options

    def replace(self, options: MoveToolOptions) -> bool:
        """Replace options and report whether configuration changed."""
        if not isinstance(options, MoveToolOptions):
            raise TypeError("options must be MoveToolOptions")
        if options == self._options:
            return False
        self._options = options
        if self._changed is not None:
            self._changed(options)
        return True
