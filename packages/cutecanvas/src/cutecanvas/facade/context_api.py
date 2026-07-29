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

"""Host-facing content context-menu requests."""

from __future__ import annotations

from PySide6.QtGui import QContextMenuEvent


class ContentContextApiMixin:
    """Resolve and publish a stable content subject for a context gesture."""

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        """Emit the addressed document subject without changing activation."""
        subject = self.contentSubject()
        if subject is None:
            event.ignore()
            return
        self.contentContextRequested.emit(subject, event.globalPos())
        event.accept()
