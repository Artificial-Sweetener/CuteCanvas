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
"""Own validation and dependency assembly for editor tool activation."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtGui import QPen

from ..editor import EditorOperation, EditorOperationTarget
from .activation import build_editor_tool_ports
from .tools import Tools

if TYPE_CHECKING:  # pragma: no cover - typing-only dependency
    from ..canvas import CuteCanvas


class EditorToolActivationController:
    """Activate one effective tool with current editor-domain collaborators."""

    def __init__(
        self,
        canvas: CuteCanvas,
        *,
        cancel_pointer_input: Callable[[], None],
        is_alt_held: Callable[[], bool],
        is_shift_held: Callable[[], bool],
        brush_size: Callable[[], int],
        preview_pens: Callable[[], tuple[QPen, QPen]],
    ) -> None:
        """Bind the canvas and dynamic activation dependency providers."""
        self._canvas = canvas
        self._cancel_pointer_input = cancel_pointer_input
        self._is_alt_held = is_alt_held
        self._is_shift_held = is_shift_held
        self._brush_size = brush_size
        self._preview_pens = preview_pens

    def accepts(self, mode: str) -> bool:
        """Return whether a registered mode can become selected now."""
        if mode not in self._canvas._tools_manager.available_modes():
            raise ValueError(f"Unknown control mode: {mode}")
        smart_modes = {
            Tools.CONTROL_MODE_SMART_SELECT,
            Tools.CONTROL_MODE_SMART_MASK,
        }
        feature_available = mode not in smart_modes or bool(
            self._canvas.samFeatureAvailable()
        )
        return (
            feature_available
            and self._canvas.editSessionCoordinator().prepare_tool_change(mode)
        )

    def activate(self, mode: str) -> bool:
        """Validate and activate one effective mode without owning selection."""
        canvas = self._canvas
        if (
            mode
            in {
                Tools.CONTROL_MODE_SMART_SELECT,
                Tools.CONTROL_MODE_SMART_MASK,
            }
            and not canvas.samFeatureAvailable()
        ):
            canvas.featureFallbacks().get("sam", "setControlMode", default=None)
            return False
        if mode not in canvas._tools_manager.available_modes():
            return False
        if mode in (
            Tools.CONTROL_MODE_DRAW_BRUSH,
            Tools.CONTROL_MODE_ERASER,
            Tools.CONTROL_MODE_CLONE_STAMP,
        ):
            self._prepare_paint_target(mode)
        ports = build_editor_tool_ports(
            canvas,
            is_alt_held=self._is_alt_held,
            is_shift_held=self._is_shift_held,
            get_brush_size=self._brush_size,
            get_preview_pens=self._preview_pens,
        )
        tools = canvas._tools_manager
        if tools.get_control_mode() != mode:
            self._cancel_pointer_input()
        tools.set_mode(mode, ports)
        return tools.get_control_mode() == mode

    def _prepare_paint_target(self, mode: str) -> None:
        """Resolve default mask creation and prioritize direct brush feedback."""
        canvas = self._canvas
        resolution = canvas.editorOperationResolver().resolve(EditorOperation.PAINT)
        mask_service = getattr(canvas, "mask_service", None)
        if (
            mode in {Tools.CONTROL_MODE_DRAW_BRUSH, Tools.CONTROL_MODE_ERASER}
            and resolution.target is EditorOperationTarget.DEFAULT_PAINT_TARGET
            and mask_service is not None
        ):
            composition_id = canvas.currentCompositionID()
            if mask_service.ensureActiveMaskForComposition(composition_id):
                mask_service.stroke_interactions.prepare_brush()
                canvas.view().coordinate_scene_descriptor()
                resolution = canvas.editorOperationResolver().resolve(
                    EditorOperation.PAINT
                )
        if (
            mode in {Tools.CONTROL_MODE_DRAW_BRUSH, Tools.CONTROL_MODE_ERASER}
            and resolution.allowed
            and mask_service is not None
        ):
            mask_service.stroke_interactions.prepare_brush()
