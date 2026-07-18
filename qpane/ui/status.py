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

"""Helpers for creating QPane status overlays from QWidget contexts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .status_overlay import QPaneStatusOverlay

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from PySide6.QtWidgets import QWidget

    from ..qpane import QPane


def create_status_overlay(
    qpane: QPane,
    *,
    parent: QWidget | None = None,
) -> QPaneStatusOverlay:
    """Create a QPaneStatusOverlay wired to the provided qpane.

    Args:
        qpane: QPane whose diagnostics will feed the overlay.
        parent: Optional QWidget host; defaults to `qpane` when omitted.

    Returns:
        QPaneStatusOverlay anchored to the resolved parent widget.
    """
    overlay_parent = parent if parent is not None else qpane
    return QPaneStatusOverlay(
        qpane=qpane,
        parent=overlay_parent,
    )
