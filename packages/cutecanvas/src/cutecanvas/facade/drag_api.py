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
"""Host-configurable outbound MIME dragging for canvas content."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtGui import QMouseEvent

from qpane.sdk.ui import DragSubject, OutboundMimeProvider

if TYPE_CHECKING:
    from ..canvas import CuteCanvas

CanvasDragSubjectResolver = Callable[
    ["CuteCanvas", QMouseEvent | None],
    DragSubject | None,
]


class OutboundDragApiMixin:
    """Expose host payload policy without coupling content to file paths."""

    def setOutboundMimeProvider(
        self,
        provider: OutboundMimeProvider,
        *,
        subject_resolver: CanvasDragSubjectResolver | None = None,
    ) -> None:
        """Install host MIME materialization and optional subject resolution."""
        if not callable(getattr(provider, "materialize", None)):
            raise TypeError("provider must implement materialize")
        if subject_resolver is not None and not callable(subject_resolver):
            raise TypeError("subject_resolver must be callable or None")
        self._outbound_mime_provider = provider
        self._drag_subject_resolver = subject_resolver

    def clearOutboundMimeProvider(self) -> None:
        """Cancel pending work and disable document drag-out."""
        self._outbound_drag.cancel()
        self._outbound_drag_subject = None
        self._outbound_mime_provider = None
        self._drag_subject_resolver = None

    def _start_outbound_drag(self, event: QMouseEvent | None) -> bool:
        """Resolve one gesture subject and begin cancellable materialization."""
        provider = self._outbound_mime_provider
        if provider is None:
            return False
        subject = self.contentSubject(event)
        if subject is None:
            return False
        self._outbound_drag_subject = subject
        self._outbound_drag.start(subject, provider)
        if event is not None:
            event.accept()
        return True

    def contentSubject(self, event: QMouseEvent | None = None) -> DragSubject | None:
        """Return the stable content subject addressed by a drag or context gesture."""
        resolver = self._drag_subject_resolver
        return (
            self._default_drag_subject() if resolver is None else resolver(self, event)
        )

    def _handle_outbound_drag_failed(self, message: str) -> None:
        """Forward materialization failure with the subject captured at gesture start."""
        subject = self._outbound_drag_subject
        if subject is not None:
            self.outboundDragFailed.emit(subject, message)

    def _default_drag_subject(self) -> DragSubject | None:
        """Address the active composition as the default inspection subject."""
        composition_id = self.currentCompositionID()
        if composition_id is None:
            return None
        record = self.compositionService().record(composition_id)
        return DragSubject(
            self.document().content_reference(composition_id),
            target_id=composition_id,
            label=record.title,
        )
