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
"""Named host interaction profiles over the authoritative capability policy."""

from __future__ import annotations

from enum import Enum

from ..types import EditorCapability, EditorPolicy


class CanvasInteractionMode(str, Enum):
    """Name common host configurations without limiting custom policies."""

    READ_ONLY = "read-only"
    MASK_AUTHORING = "mask-authoring"
    FULL_EDITOR = "full-editor"
    CUSTOM = "custom"


_MASK_CAPABILITIES = frozenset(
    {
        EditorCapability.SELECT_PIXELS,
        EditorCapability.EDIT_PIXELS,
        EditorCapability.PAINT,
        EditorCapability.MOVE_LAYERS,
        EditorCapability.TRANSFORM_LAYERS,
    }
)


def editor_policy_for_mode(mode: CanvasInteractionMode) -> EditorPolicy:
    """Return the one capability policy represented by a named profile."""
    resolved = CanvasInteractionMode(mode)
    if resolved is CanvasInteractionMode.CUSTOM:
        raise ValueError("custom mode requires an explicit EditorPolicy")
    if resolved is CanvasInteractionMode.READ_ONLY:
        return EditorPolicy(frozenset())
    if resolved is CanvasInteractionMode.MASK_AUTHORING:
        return EditorPolicy(_MASK_CAPABILITIES)
    return EditorPolicy()


def mode_for_editor_policy(policy: EditorPolicy) -> CanvasInteractionMode:
    """Return a named profile when an exact capability set matches."""
    if policy == editor_policy_for_mode(CanvasInteractionMode.READ_ONLY):
        return CanvasInteractionMode.READ_ONLY
    if policy == editor_policy_for_mode(CanvasInteractionMode.MASK_AUTHORING):
        return CanvasInteractionMode.MASK_AUTHORING
    if policy == editor_policy_for_mode(CanvasInteractionMode.FULL_EDITOR):
        return CanvasInteractionMode.FULL_EDITOR
    return CanvasInteractionMode.CUSTOM
