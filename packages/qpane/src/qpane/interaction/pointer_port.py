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
"""Host boundary consumed by QPane's normalized pointer controller."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtWidgets import QWidget

from .tool import ViewerTool
from .touch_navigation import DirectManipulationViewport


def _false() -> bool:
    """Return the inert false-valued port default."""
    return False


def _true() -> bool:
    """Return the permissive true-valued port default."""
    return True


def _none() -> None:
    """Perform no work for an optional host callback."""


@dataclass(frozen=True, slots=True)
class PointerInputPort:
    """Supply source-neutral tool, viewport, policy, and gesture collaborators."""

    widget: QWidget
    active_tool: Callable[[], ViewerTool | None]
    viewport: Callable[[], DirectManipulationViewport]
    physical_viewport_rect: Callable[[], QRectF]
    has_renderable_content: Callable[[], bool]
    touch_navigation_enabled: Callable[[], bool] = _true
    touch_tool_enabled: Callable[[], bool] = _false
    stylus_tool_enabled: Callable[[], bool] = _false
    touch_inertia_enabled: Callable[[], bool] = _true
    touch_inertia_deceleration: Callable[[], float] = lambda: 4500.0
    palm_rejection_ms: Callable[[], int] = lambda: 800
    claim_external_touch: Callable[[QPointF], bool] = lambda _position: False
    update_external_touch: Callable[[QPointF], None] = lambda _position: None
    finish_external_touch: Callable[[QPointF], None] = lambda _position: None
    cancel_external_touch: Callable[[], None] = _none
    pointer_state_changed: Callable[[], None] = _none
