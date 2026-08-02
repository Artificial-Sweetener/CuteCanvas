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

"""Move-tool configuration facade."""

from __future__ import annotations

from cutecanvas.types import MoveToolOptions


class MoveApiMixin:
    """Expose immutable direct-layer movement options."""

    def moveToolOptions(self) -> MoveToolOptions:
        """Return current Move-tool options."""
        return self._move_tool_configuration.options

    def setMoveToolOptions(self, options: MoveToolOptions) -> bool:
        """Replace Move-tool options after cancelling provisional movement."""
        if not isinstance(options, MoveToolOptions):
            raise TypeError("options must be MoveToolOptions")
        if options == self._move_tool_configuration.options:
            return False
        movement = self._editor_movement_interaction
        if movement is not None:
            movement.cancel()
            movement.clear_hover()
        changed = self._move_tool_configuration.replace(options)
        if changed:
            self.refreshCursor()
            self.update()
        return changed
