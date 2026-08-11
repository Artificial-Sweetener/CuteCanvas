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

"""Focused activation ports for affine editor tools."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPointF
from qpane.sdk.scene import TransformModifiers, TransformOperation

from cutecanvas.editor.shared_edge_presentation import SharedEdgePresentation
from cutecanvas.editor.transform_interaction import TransformBoxPresentation


def _false() -> bool:
    """Return the inert false-valued tool default."""
    return False


@dataclass(frozen=True, slots=True)
class TransformInteractionPort:
    """Dependencies used by source-neutral affine transform interaction."""

    transform_presentation: Callable[[], TransformBoxPresentation | None] = lambda: None
    begin_transform: Callable[[TransformOperation, QPointF], bool] = (
        lambda _operation, _point: False
    )
    update_transform: Callable[[QPointF, TransformModifiers], bool] = (
        lambda _point, _modifiers: False
    )
    end_transform_gesture: Callable[[QPointF, TransformModifiers], bool] = (
        lambda _point, _modifiers: False
    )
    commit_transform: Callable[[], bool] = _false
    cancel_transform: Callable[[], bool] = _false
    suspend_transform: Callable[[], bool] = _false


@dataclass(frozen=True, slots=True)
class SharedEdgeResizePort:
    """Dependencies used by coupled two-layer seam resizing."""

    presentation: Callable[[], SharedEdgePresentation | None] = lambda: None
    update_hover: Callable[[QPointF], bool] = lambda _point: False
    clear_hover: Callable[[], bool] = _false
    begin: Callable[[QPointF], bool] = lambda _point: False
    update: Callable[[QPointF], bool] = lambda _point: False
    finish: Callable[[QPointF], bool] = lambda _point: False
    apply: Callable[[], bool] = _false
    cancel: Callable[[], bool] = _false
    suspend: Callable[[], bool] = _false


__all__ = ["SharedEdgeResizePort", "TransformInteractionPort"]
