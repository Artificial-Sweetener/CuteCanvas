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
"""Explicit eraser painting mode built on the shared brush interaction."""

from __future__ import annotations

from typing import ClassVar

from PySide6.QtCore import Qt

from .brush import BrushTool


class EraserTool(BrushTool):
    """Erase every stroke without interpreting Alt as a mode inversion."""

    supports_alt_erase_indicator: ClassVar[bool] = False

    def _erase_mode(
        self,
        modifiers: Qt.KeyboardModifier,
        *,
        eraser_device: bool = False,
    ) -> bool:
        """Keep the explicit eraser operation stable for every input device."""

        del modifiers, eraser_device
        return True


__all__ = ["EraserTool"]
