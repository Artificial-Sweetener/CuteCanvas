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
"""Headless document and detachable view-session public values."""

from .canvas_geometry import CanvasAnchor
from .canvas_resampling import CanvasResamplingMode
from .document import CanvasDocument
from .events import DocumentChange, DocumentChangeKind, DocumentEventHub
from .history import DocumentHistory
from .references import (
    CanvasContentKind,
    CanvasContentReference,
    ResolvedCanvasContent,
)
from .session import (
    CanvasComparison,
    CanvasInspectionGroup,
    CanvasPresentation,
    CanvasPresentationKind,
    CanvasSessionSnapshot,
    CanvasViewSession,
)
from .viewport import (
    CanvasRenderVariant,
    CanvasViewportInteraction,
    CanvasViewportSource,
    CanvasViewportSpec,
)

__all__ = [
    "CanvasAnchor",
    "CanvasComparison",
    "CanvasContentKind",
    "CanvasContentReference",
    "CanvasDocument",
    "CanvasInspectionGroup",
    "CanvasPresentation",
    "CanvasPresentationKind",
    "CanvasRenderVariant",
    "CanvasResamplingMode",
    "CanvasSessionSnapshot",
    "CanvasViewSession",
    "CanvasViewportInteraction",
    "CanvasViewportSource",
    "CanvasViewportSpec",
    "DocumentChange",
    "DocumentChangeKind",
    "DocumentEventHub",
    "DocumentHistory",
    "ResolvedCanvasContent",
]
