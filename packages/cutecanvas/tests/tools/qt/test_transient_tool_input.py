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
"""Exercise the pure persistent/transient tool-state owner."""

from __future__ import annotations

import pytest
from cutecanvas.tools.tools import Tools
from cutecanvas.tools.transient_input import TransientToolInput


class _ToolInputProbe:
    """Record every collaborator call made by transient tool resolution."""

    def __init__(self) -> None:
        """Initialize permissive activation and inactive text capture."""
        self.activations: list[str] = []
        self.suspensions = 0
        self.state_changes = 0
        self.capture_space = False
        self.rejected: set[str] = set()

    def activate(self, mode: str) -> bool:
        """Record and accept one effective activation."""
        self.activations.append(mode)
        return True

    def accepts(self, mode: str) -> bool:
        """Reject only modes explicitly marked by the test."""
        return mode not in self.rejected

    def suspend(self) -> None:
        """Record one in-flight gesture suspension."""
        self.suspensions += 1

    def changed(self) -> None:
        """Record one semantic state publication."""
        self.state_changes += 1

    def owner(self) -> TransientToolInput:
        """Build the production state owner around this probe."""
        return TransientToolInput(
            navigation_mode=Tools.CONTROL_MODE_PANZOOM,
            activate=self.activate,
            accepts=self.accepts,
            suspend_active_tool=self.suspend,
            active_tool_captures_space=lambda: self.capture_space,
            state_changed=self.changed,
        )


@pytest.mark.parametrize(
    "mode",
    (
        Tools.CONTROL_MODE_CURSOR,
        Tools.CONTROL_MODE_MOVE,
        Tools.CONTROL_MODE_TRANSFORM,
        Tools.CONTROL_MODE_DRAW_BRUSH,
        Tools.CONTROL_MODE_ERASER,
        Tools.CONTROL_MODE_CLONE_STAMP,
        Tools.CONTROL_MODE_PAINT_BUCKET,
        Tools.CONTROL_MODE_SMART_SELECT,
        Tools.CONTROL_MODE_SELECT_RECTANGLE,
        Tools.CONTROL_MODE_SELECT_ELLIPSE,
        Tools.CONTROL_MODE_SELECT_LASSO,
        Tools.CONTROL_MODE_SELECT_POLYGON,
        Tools.CONTROL_MODE_MASK_RECTANGLE,
        Tools.CONTROL_MODE_MASK_ELLIPSE,
        Tools.CONTROL_MODE_MASK_LASSO,
        Tools.CONTROL_MODE_MASK_POLYGON,
    ),
)
def test_space_temporarily_navigates_from_every_compatible_tool(mode: str) -> None:
    """Every editor tool restores exactly after repeated Space events."""
    probe = _ToolInputProbe()
    owner = probe.owner()
    assert owner.select_mode(mode)

    assert owner.press_space(auto_repeat=False)
    assert owner.press_space(auto_repeat=True)
    assert owner.release_space(auto_repeat=True)
    assert owner.release_space(auto_repeat=False)

    assert owner.selected_mode == mode
    assert probe.activations == [mode, Tools.CONTROL_MODE_PANZOOM, mode]
    assert probe.suspensions == 1


def test_modifier_precedence_and_tool_changes_remain_deterministic() -> None:
    """Alt, Shift, Space, repeats, and selection changes never overwrite state."""
    probe = _ToolInputProbe()
    owner = probe.owner()
    assert owner.select_mode(Tools.CONTROL_MODE_DRAW_BRUSH)
    assert owner.press_alt(auto_repeat=False)
    assert owner.press_shift(auto_repeat=False)
    assert owner.press_space(auto_repeat=False)
    assert owner.select_mode(Tools.CONTROL_MODE_MASK_LASSO)
    assert owner.press_alt(auto_repeat=True)
    assert owner.release_shift(auto_repeat=False)

    assert owner.alt_held
    assert not owner.shift_held
    assert owner.space_held
    assert owner.selected_mode == Tools.CONTROL_MODE_MASK_LASSO
    assert probe.activations[-1] == Tools.CONTROL_MODE_PANZOOM

    assert owner.release_space(auto_repeat=False)
    assert probe.activations[-1] == Tools.CONTROL_MODE_MASK_LASSO
    assert owner.release_alt(auto_repeat=False)
    assert not owner.alt_held


def test_alt_never_selects_the_explicit_eraser() -> None:
    """Alt changes modifier state without replacing the persistent brush tool."""

    probe = _ToolInputProbe()
    owner = probe.owner()
    assert owner.select_mode(Tools.CONTROL_MODE_DRAW_BRUSH)

    assert owner.press_alt(auto_repeat=False)

    assert owner.selected_mode == Tools.CONTROL_MODE_DRAW_BRUSH
    assert probe.activations == [Tools.CONTROL_MODE_DRAW_BRUSH]


def test_lifecycle_reset_restores_selection_and_clears_every_modifier() -> None:
    """Focus or visibility loss cannot leave navigation or subtraction sticky."""
    probe = _ToolInputProbe()
    owner = probe.owner()
    assert owner.select_mode(Tools.CONTROL_MODE_MASK_ELLIPSE)
    assert owner.press_alt(auto_repeat=False)
    assert owner.press_shift(auto_repeat=False)
    assert owner.press_space(auto_repeat=False)

    owner.reset()

    assert not owner.alt_held
    assert not owner.shift_held
    assert not owner.space_held
    assert probe.activations[-1] == Tools.CONTROL_MODE_MASK_ELLIPSE


def test_literal_space_capture_and_rejected_selection_preserve_state() -> None:
    """Text ownership and invalid modes do not mutate persistent selection."""
    probe = _ToolInputProbe()
    owner = probe.owner()
    assert owner.select_mode(Tools.CONTROL_MODE_DRAW_BRUSH)
    probe.capture_space = True
    assert not owner.press_space(auto_repeat=False)
    probe.rejected.add("unavailable")
    assert not owner.select_mode("unavailable")

    assert owner.selected_mode == Tools.CONTROL_MODE_DRAW_BRUSH
    assert not owner.space_held
    assert probe.activations == [Tools.CONTROL_MODE_DRAW_BRUSH]
