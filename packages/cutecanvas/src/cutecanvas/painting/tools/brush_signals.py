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
"""Tool-manager signal binding for every shared brush specialization."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from cutecanvas.tools.base import BaseTool

if TYPE_CHECKING:
    from cutecanvas.tools.tools import ToolManagerSignals

logger = logging.getLogger(__name__)

_BRUSH_SIGNAL_MAPPINGS: tuple[tuple[str, str], ...] = (
    ("stroke_applied", "stroke_applied"),
    ("brush_size_changed", "brush_size_changed"),
    ("stroke_completed", "stroke_completed"),
    ("stroke_cancelled", "stroke_cancelled"),
    ("undo_state_push_requested", "undo_state_push_requested"),
)


def connect_brush_signals(
    manager_signals: ToolManagerSignals,
    tool: BaseTool,
) -> None:
    """Bridge brush-tool emissions into the editor tool-manager contract."""
    for tool_attr, manager_attr in _BRUSH_SIGNAL_MAPPINGS:
        signal = getattr(tool.signals, tool_attr, None)
        if signal is None:
            raise AttributeError(
                f"{type(tool).__name__} is missing required signal "
                f"'{tool_attr}'. Update its signal contract before wiring."
            )
        target = getattr(manager_signals, manager_attr, None)
        if target is None:
            raise AttributeError(
                f"ToolManagerSignals no longer expose '{manager_attr}'. "
                "Update the signal mapping to match."
            )
        signal.connect(target)


def disconnect_brush_signals(
    manager_signals: ToolManagerSignals,
    tool: BaseTool,
) -> None:
    """Tear down the shared brush-tool signal contract with diagnostics."""
    for tool_attr, manager_attr in _BRUSH_SIGNAL_MAPPINGS:
        signal = getattr(tool.signals, tool_attr, None)
        target = getattr(manager_signals, manager_attr, None)
        if signal is None or target is None:
            logger.warning(
                "Skipping disconnect for '%s' -> '%s'; signal contract drift detected.",
                tool_attr,
                manager_attr,
            )
            continue
        try:
            signal.disconnect(target)
        except (TypeError, RuntimeError) as exc:
            logger.warning(
                "Failed to disconnect brush signal '%s': %s",
                tool_attr,
                exc,
            )
