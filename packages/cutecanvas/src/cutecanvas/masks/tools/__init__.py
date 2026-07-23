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

"""Mask-specific smart-selection tool registrations and helpers."""

from .smart_select import (
    SmartSelectTool,
    connect_smart_select_signals,
    disconnect_smart_select_signals,
    smart_select_cursor_provider,
)

__all__ = (
    "SmartSelectTool",
    "connect_smart_select_signals",
    "disconnect_smart_select_signals",
    "smart_select_cursor_provider",
)
