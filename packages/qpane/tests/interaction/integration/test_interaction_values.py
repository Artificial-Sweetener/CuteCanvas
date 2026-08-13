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
"""Characterization for QPane-owned source-neutral interaction values."""

from PySide6.QtCore import QPointF, Qt

from qpane import (
    PointerDeviceKind,
    PointerPhase,
    PointerSample,
    ToolInputProfile,
    TouchGestureArena,
    TouchGestureKind,
)


def test_pointer_sample_detaches_qt_positions() -> None:
    """Pointer observations cannot change when caller-owned points mutate."""
    position = QPointF(12.0, 18.0)
    global_position = QPointF(42.0, 58.0)
    sample = PointerSample(
        pointer_id=7,
        device=PointerDeviceKind.PEN,
        phase=PointerPhase.BEGIN,
        position=position,
        global_position=global_position,
        pressure=0.5,
        buttons=Qt.MouseButton.LeftButton,
        modifiers=Qt.KeyboardModifier.ShiftModifier,
        timestamp_ms=123,
    )

    position.setX(99.0)
    global_position.setY(99.0)

    assert sample.position == QPointF(12.0, 18.0)
    assert sample.global_position == QPointF(42.0, 58.0)
    assert sample.is_contact


def test_touch_arena_keeps_one_stable_winner() -> None:
    """A multi-contact navigation decision cannot later become a direct tool."""
    arena = TouchGestureArena(movement_threshold=6.0)
    arena.begin(navigation_mode=False, direct_tool_allowed=True)

    assert arena.kind is TouchGestureKind.PENDING
    assert (
        arena.evaluate(contact_count=2, primary_distance=1.0)
        is TouchGestureKind.NAVIGATION
    )
    assert (
        arena.evaluate(contact_count=1, primary_distance=100.0, ending=True)
        is TouchGestureKind.NAVIGATION
    )


def test_input_profile_defaults_are_inert() -> None:
    """An extension must opt into every direct-input capability."""
    assert ToolInputProfile() == ToolInputProfile(
        navigation=False,
        touch=False,
        tablet=False,
        touch_requires_host_enablement=False,
        tablet_requires_host_enablement=False,
        touch_preview=False,
    )
