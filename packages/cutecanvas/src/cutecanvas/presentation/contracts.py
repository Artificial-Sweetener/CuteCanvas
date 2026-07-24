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
"""Public extension contracts for document presentation surfaces."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from PySide6.QtWidgets import QWidget

if TYPE_CHECKING:
    from ..canvas import CuteCanvas
    from ..document import CanvasDocument, CanvasViewSession

CanvasViewFactory = Callable[[uuid.UUID, QWidget], "CuteCanvas"]


@dataclass(frozen=True, slots=True)
class CanvasPresentationContext:
    """Give one host provider document targets and supported view creation."""

    document: CanvasDocument
    session: CanvasViewSession
    target_ids: tuple[uuid.UUID, ...]
    create_view: CanvasViewFactory


class CanvasPresentationProvider(Protocol):
    """Build a host-defined surface without taking ownership of document state."""

    @property
    def presentation_id(self) -> str:
        """Return the stable non-empty identifier used by session state."""
        ...

    def create_widget(
        self,
        context: CanvasPresentationContext,
        parent: QWidget,
    ) -> QWidget:
        """Create one presentation widget using supported context operations."""
        ...
