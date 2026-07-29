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
"""Resolve persistent tool selection and transient editor modifiers."""

from __future__ import annotations

from collections.abc import Callable


class TransientToolInput:
    """Keep modifier lifetime independent from persistent tool selection."""

    def __init__(
        self,
        *,
        navigation_mode: str,
        activate: Callable[[str], bool],
        accepts: Callable[[str], bool],
        suspend_active_tool: Callable[[], None],
        active_tool_captures_space: Callable[[], bool],
        state_changed: Callable[[], None],
    ) -> None:
        """Bind effective-mode and feedback collaborators."""
        self._navigation_mode = navigation_mode
        self._activate = activate
        self._accepts = accepts
        self._suspend_active_tool = suspend_active_tool
        self._active_tool_captures_space = active_tool_captures_space
        self._state_changed = state_changed
        self._selected_mode = navigation_mode
        self._space_held = False
        self._alt_held = False
        self._shift_held = False

    @property
    def selected_mode(self) -> str:
        """Return the persistent tool chosen by the host or user."""
        return self._selected_mode

    @property
    def alt_held(self) -> bool:
        """Return whether subtraction is temporarily requested."""
        return self._alt_held

    @property
    def shift_held(self) -> bool:
        """Return whether the tool-specific Shift modifier is held."""
        return self._shift_held

    @property
    def space_held(self) -> bool:
        """Return whether temporary navigation currently owns the tool."""
        return self._space_held

    def select_mode(self, mode: str) -> bool:
        """Select ``mode`` while leaving Space-owned navigation effective."""
        if not self._accepts(mode):
            return False
        previous = self._selected_mode
        self._selected_mode = mode
        if self._space_held:
            self._state_changed()
            return True
        if self._activate(mode):
            self._state_changed()
            return True
        self._selected_mode = previous
        return False

    def press_alt(self, *, auto_repeat: bool) -> bool:
        """Begin subtractive operation mode once."""
        if not auto_repeat and not self._alt_held:
            self._alt_held = True
            self._state_changed()
        return True

    def release_alt(self, *, auto_repeat: bool) -> bool:
        """End subtractive operation mode once."""
        if not auto_repeat and self._alt_held:
            self._alt_held = False
            self._state_changed()
        return True

    def press_shift(self, *, auto_repeat: bool) -> bool:
        """Begin the tool-specific Shift modifier once."""
        if not auto_repeat and not self._shift_held:
            self._shift_held = True
            self._state_changed()
        return True

    def release_shift(self, *, auto_repeat: bool) -> bool:
        """End the tool-specific Shift modifier once."""
        if not auto_repeat and self._shift_held:
            self._shift_held = False
            self._state_changed()
        return True

    def press_space(self, *, auto_repeat: bool) -> bool:
        """Temporarily activate navigation without replacing selection."""
        if self._active_tool_captures_space():
            return False
        if auto_repeat or self._space_held:
            return True
        self._suspend_active_tool()
        if not self._activate(self._navigation_mode):
            return False
        self._space_held = True
        self._state_changed()
        return True

    def release_space(self, *, auto_repeat: bool) -> bool:
        """Restore the latest persistent selection after navigation."""
        if auto_repeat:
            return True
        if self._space_held:
            self._space_held = False
            self._activate(self._selected_mode)
            self._state_changed()
        return True

    def reset(self) -> None:
        """Clear sticky modifiers and restore selection after lifecycle loss."""
        restore_selection = self._space_held
        changed = restore_selection or self._alt_held or self._shift_held
        self._space_held = False
        self._alt_held = False
        self._shift_held = False
        if restore_selection:
            self._activate(self._selected_mode)
        if changed:
            self._state_changed()
