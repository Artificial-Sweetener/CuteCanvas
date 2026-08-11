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

"""Close widget-owned resources before Qt begins destroying child objects."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QWidget


class WidgetOwnerLifetimeGuard(QObject):
    """Bind one widget's resource cleanup to its effective Qt lifetime."""

    def __init__(self, widget: QWidget, close_owners: Callable[[], None]) -> None:
        """Observe direct deletion, reparenting, and enclosing-parent teardown."""
        super().__init__(widget)
        self._widget: QWidget | None = widget
        self._close_owners: Callable[[], None] | None = close_owners
        self._lifetime_parent: QWidget | None = None
        widget.installEventFilter(self)
        self._bind_parent()

    def detach(self) -> None:
        """Stop lifetime observation after the owned resources have closed."""
        widget = self._widget
        self._widget = None
        self._close_owners = None
        if widget is not None:
            try:
                widget.removeEventFilter(self)
            except RuntimeError:
                pass
        self._unbind_parent()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Observe ownership changes without consuming the widget event."""
        if watched is self._widget:
            event_type = event.type()
            if event_type == QEvent.Type.DeferredDelete:
                self._request_close()
            elif event_type == QEvent.Type.ParentChange:
                self._bind_parent()
        return False

    def _bind_parent(self) -> None:
        """Subscribe to the widget's current enclosing Qt owner."""
        widget = self._widget
        parent = None if widget is None else widget.parentWidget()
        if parent is self._lifetime_parent:
            return
        self._unbind_parent()
        self._lifetime_parent = parent
        if parent is not None:
            parent.destroyed.connect(self._parent_destroyed)

    def _unbind_parent(self) -> None:
        """Remove the current enclosing-owner subscription when still valid."""
        parent = self._lifetime_parent
        self._lifetime_parent = None
        if parent is None:
            return
        try:
            parent.destroyed.disconnect(self._parent_destroyed)
        except (RuntimeError, TypeError):
            pass

    def _parent_destroyed(self, _owner: object | None = None) -> None:
        """Close resources before the enclosing owner deletes this widget."""
        self._lifetime_parent = None
        self._request_close()

    def _request_close(self) -> None:
        """Invoke the live resource owner exactly through its idempotent boundary."""
        close_owners = self._close_owners
        if close_owners is not None:
            close_owners()


__all__ = ["WidgetOwnerLifetimeGuard"]
