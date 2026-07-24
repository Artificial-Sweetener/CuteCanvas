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

"""Internal composition records used by the composition service."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QRectF


class CompositionOrigin(str, Enum):
    """Describe the one independent editor-document origin."""

    COMPOSITION = "composition"


@dataclass(frozen=True, slots=True)
class CompositionDocumentPolicy:
    """Host-selected structural policy for one composition."""

    removable: bool = True


@dataclass(frozen=True, slots=True)
class CompositionRecord:
    """Persistent composition document state independent of its layer sources."""

    composition_id: uuid.UUID
    origin: CompositionOrigin
    title: str
    canvas_bounds: QRectF
    policy: CompositionDocumentPolicy = CompositionDocumentPolicy()

    def __post_init__(self) -> None:
        """Validate and detach mutable canvas geometry from the stored record."""
        bounds = QRectF(self.canvas_bounds)
        if bounds.width() <= 0.0 or bounds.height() <= 0.0:
            raise ValueError("composition canvas bounds must be positive")
        object.__setattr__(self, "canvas_bounds", bounds)
