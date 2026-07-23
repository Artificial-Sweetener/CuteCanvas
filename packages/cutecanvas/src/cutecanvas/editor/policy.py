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
"""Host editor-capability policy ownership."""

from __future__ import annotations

from collections.abc import Callable

from ..types import EditorCapability, EditorPolicy


class EditorPolicyController:
    """Own the active composable host policy and publish exact replacements."""

    def __init__(self, changed: Callable[[EditorPolicy], None]) -> None:
        """Initialize the full editor policy used for compatibility."""
        self._policy = EditorPolicy()
        self._changed = changed

    @property
    def policy(self) -> EditorPolicy:
        """Return the immutable current host policy."""
        return self._policy

    def allows(self, capability: EditorCapability) -> bool:
        """Return whether the current host policy includes one capability."""
        return EditorCapability(capability) in self._policy.capabilities

    def replace(self, policy: EditorPolicy) -> bool:
        """Replace the complete policy and publish a real change once."""
        if not isinstance(policy, EditorPolicy):
            raise TypeError("policy must be EditorPolicy")
        if policy == self._policy:
            return False
        self._policy = policy
        self._changed(policy)
        return True
