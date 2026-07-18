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

"""Qt-focused helpers that keep QPane's QWidget facade slim."""

from __future__ import annotations

from .clipboard import copyToClipboard
from .cursor_builder import CursorBuilder
from .dragdrop import drag_out_image, is_drag_out_allowed
from .dragout import maybeStartDrag
from .overlays import (
    maybe_resume_overlays,
    resume_overlays,
    resume_overlays_and_update,
)
from .status import create_status_overlay
from .widget_props import apply_widget_defaults

__all__ = [
    "CursorBuilder",
    "apply_widget_defaults",
    "copyToClipboard",
    "create_status_overlay",
    "drag_out_image",
    "is_drag_out_allowed",
    "maybeStartDrag",
    "maybe_resume_overlays",
    "resume_overlays",
    "resume_overlays_and_update",
]
