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
"""Reconcile cached keyboard state with authoritative pointer snapshots."""

from __future__ import annotations

from PySide6.QtCore import Qt


def modifier_is_active(
    cached_state: bool,
    pointer_modifiers: Qt.KeyboardModifier,
    modifier: Qt.KeyboardModifier,
) -> bool:
    """Return a modifier state that survives focus and activation transitions.

    Pointer events report the physical modifier snapshot even when a focus change
    prevented the canvas from observing the corresponding key press.
    """

    return bool(cached_state or pointer_modifiers & modifier)


def alt_is_active(
    cached_state: bool,
    pointer_modifiers: Qt.KeyboardModifier,
) -> bool:
    """Return the reconciled subtractive modifier state."""

    return modifier_is_active(
        cached_state,
        pointer_modifiers,
        Qt.KeyboardModifier.AltModifier,
    )


def shift_is_active(
    cached_state: bool,
    pointer_modifiers: Qt.KeyboardModifier,
) -> bool:
    """Return the reconciled shape-constraint modifier state."""

    return modifier_is_active(
        cached_state,
        pointer_modifiers,
        Qt.KeyboardModifier.ShiftModifier,
    )


def snapping_is_suppressed(pointer_modifiers: Qt.KeyboardModifier) -> bool:
    """Return whether Control temporarily suppresses authoring snapping."""
    return bool(pointer_modifiers & Qt.KeyboardModifier.ControlModifier)
