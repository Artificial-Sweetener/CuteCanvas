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
"""Source-neutral pointer and tool-interaction values owned by QPane."""

from .arena import TouchGestureArena, TouchGestureKind
from .cursor_tool import CursorTool
from .navigation_tool import PanZoomTool
from .pointer import PointerDeviceKind, PointerPhase, PointerSample
from .pointer_controller import PointerInputController
from .pointer_port import PointerInputPort
from .ports import CursorInteractionPort, NavigationInteractionPort, ToolDependencies
from .profile import ToolInputProfile
from .tool import ViewerTool, ViewerToolSignals
from .tool_manager import ToolManager, ToolManagerSignals
from .touch_navigation import TouchNavigationPort, TouchNavigationSession
from .viewer_controller import ViewerInteractionController, ViewerInteractionHost

__all__ = [
    "CursorInteractionPort",
    "CursorTool",
    "NavigationInteractionPort",
    "PanZoomTool",
    "PointerDeviceKind",
    "PointerInputController",
    "PointerInputPort",
    "PointerPhase",
    "PointerSample",
    "ToolDependencies",
    "ToolInputProfile",
    "ToolManager",
    "ToolManagerSignals",
    "TouchGestureArena",
    "TouchGestureKind",
    "TouchNavigationPort",
    "TouchNavigationSession",
    "ViewerInteractionController",
    "ViewerInteractionHost",
    "ViewerTool",
    "ViewerToolSignals",
]
