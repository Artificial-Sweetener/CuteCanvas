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

"""Widget configuration helpers for QPane's Qt facade."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSizePolicy, QWidget


def apply_widget_defaults(widget: QWidget) -> None:
    """Configure QPane's QWidget defaults such as translucency and tracking.

    Args:
        widget: QWidget that should adopt the baseline drawing and sizing contract.
    """
    widget.setAttribute(Qt.WA_TranslucentBackground)
    widget.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)
    widget.setMouseTracking(True)
    widget.setTabletTracking(True)
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    widget.setMinimumSize(1, 1)
