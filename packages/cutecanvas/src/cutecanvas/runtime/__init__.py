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
"""Focused CuteCanvas runtime responsibilities."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .document_runtime import CanvasDocumentRuntime

__all__ = ["CanvasDocumentRuntime"]


def __getattr__(name: str):
    """Load the public document runtime without eager document imports."""
    if name != "CanvasDocumentRuntime":
        raise AttributeError(name)
    value = import_module(".document_runtime", __name__).CanvasDocumentRuntime
    globals()[name] = value
    return value
