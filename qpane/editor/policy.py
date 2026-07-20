#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Host editor-capability policy ownership."""

from __future__ import annotations

from collections.abc import Callable

from ..types import EditorCapability, QPaneEditorPolicy


class EditorPolicyController:
    """Own the active composable host policy and publish exact replacements."""

    def __init__(self, changed: Callable[[QPaneEditorPolicy], None]) -> None:
        """Initialize the full editor policy used for compatibility."""
        self._policy = QPaneEditorPolicy()
        self._changed = changed

    @property
    def policy(self) -> QPaneEditorPolicy:
        """Return the immutable current host policy."""
        return self._policy

    def allows(self, capability: EditorCapability) -> bool:
        """Return whether the current host policy includes one capability."""
        return EditorCapability(capability) in self._policy.capabilities

    def replace(self, policy: QPaneEditorPolicy) -> bool:
        """Replace the complete policy and publish a real change once."""
        if not isinstance(policy, QPaneEditorPolicy):
            raise TypeError("policy must be QPaneEditorPolicy")
        if policy == self._policy:
            return False
        self._policy = policy
        self._changed(policy)
        return True
