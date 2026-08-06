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
    from .canvas_resampling import CanvasResamplingResult, CanvasResamplingStatus
    from .document_runtime import CanvasDocumentRuntime

__all__ = [
    "CanvasDocumentRuntime",
    "CanvasResamplingResult",
    "CanvasResamplingStatus",
]


def __getattr__(name: str):
    """Load the public document runtime without eager document imports."""
    targets = {
        "CanvasDocumentRuntime": (".document_runtime", "CanvasDocumentRuntime"),
        "CanvasResamplingResult": (
            ".canvas_resampling",
            "CanvasResamplingResult",
        ),
        "CanvasResamplingStatus": (
            ".canvas_resampling",
            "CanvasResamplingStatus",
        ),
    }
    target = targets.get(name)
    if target is None:
        raise AttributeError(name)
    value = getattr(import_module(target[0], __name__), target[1])
    globals()[name] = value
    return value
