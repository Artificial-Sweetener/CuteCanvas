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

"""Tool plumbing helpers for QPane's internal interaction stack."""

from __future__ import annotations

import sys
from typing import Any

from .base import CursorTool, ExtensionTool, ExtensionToolSignals, PanZoomTool
from .dependencies import ToolDependencies
from .tools import ToolManagerSignals, Tools

__all__ = [
    "CursorTool",
    "ExtensionTool",
    "ExtensionToolSignals",
    "PanZoomTool",
    "ToolDependencies",
    "ToolManagerSignals",
    "Tools",
]

# Expose the module under a stable attribute so qpane.__getattr__("tools") returns it.
tools = sys.modules[__name__]


def __getattr__(name: str) -> Any:
    """Lazily resolve heavy imports to avoid circular dependencies."""
    raise AttributeError(f"module {__name__!s} has no attribute {name}")
