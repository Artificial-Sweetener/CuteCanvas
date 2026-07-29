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
"""Focused activation ports for QPane's built-in viewer tools."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeAlias

from PySide6.QtCore import QPoint, QPointF

if TYPE_CHECKING:
    from ..rendering.viewport import ViewportZoomMode


def _false() -> bool:
    """Return the inert false-valued tool default."""
    return False


def _true() -> bool:
    """Return the safe true-valued tool guard default."""
    return True


def _none() -> None:
    """Perform no action for an optional tool command."""


def _point_zero() -> QPointF:
    """Return a detached zero-valued point."""
    return QPointF()


def _one() -> float:
    """Return the neutral zoom or device-pixel ratio."""
    return 1.0


def _one_at(_point: QPointF) -> float:
    """Return neutral native zoom for one unconfigured panel point."""

    return 1.0


ToolDependencies: TypeAlias = Mapping[str, object]


@dataclass(frozen=True, slots=True)
class CursorInteractionPort:
    """Dependencies used by the inert cursor and drag-out interaction."""

    is_drag_out_allowed: Callable[[], bool] = _false
    is_content_empty: Callable[[], bool] = _true


@dataclass(frozen=True, slots=True)
class NavigationInteractionPort:
    """Dependencies used by pan, wheel zoom, and fit snapping."""

    is_navigation_locked: Callable[[], bool] = _true
    is_content_empty: Callable[[], bool] = _true
    is_drag_out_allowed: Callable[[], bool] = _false
    can_pan: Callable[[], bool] = _false
    get_pan: Callable[[], QPointF] = _point_zero
    get_zoom: Callable[[], float] = _one
    get_native_zoom: Callable[[QPointF], float] = _one_at
    get_fit_zoom: Callable[[], float] = _one
    get_zoom_mode: Callable[[], ViewportZoomMode] | None = None
    set_zoom_fit: Callable[[], None] = _none
    set_zoom_fit_interpolated: Callable[[], None] | None = None
    set_zoom_one_to_one: Callable[[QPoint | QPointF | None], None] = (
        lambda _anchor=None: None
    )
    set_zoom_one_to_one_interpolated: (
        Callable[[QPoint | QPointF | None], None] | None
    ) = None
    get_dpr: Callable[[], float] = _one
