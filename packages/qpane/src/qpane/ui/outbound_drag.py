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
"""General cancellable MIME drag materialization and native execution."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from PySide6.QtCore import (
    QByteArray,
    QMimeData,
    QObject,
    QPoint,
    QSize,
    Qt,
    QUrl,
    Signal,
)
from PySide6.QtGui import QDrag, QImage, QPixmap
from PySide6.QtWidgets import QWidget


@dataclass(frozen=True, slots=True)
class DragSubject:
    """Identify host content selected by a drag gesture."""

    subject_id: object
    target_id: uuid.UUID | None = None
    label: str | None = None


@dataclass(frozen=True, slots=True)
class OutboundMimeItem:
    """Carry one arbitrary MIME value as detached bytes."""

    mime_type: str
    data: bytes

    def __post_init__(self) -> None:
        """Validate MIME identity and detach byte-like payloads."""
        mime_type = self.mime_type.strip()
        if not mime_type or "/" not in mime_type:
            raise ValueError("mime_type must be a non-empty MIME identifier")
        object.__setattr__(self, "mime_type", mime_type)
        object.__setattr__(self, "data", bytes(self.data))


@dataclass(frozen=True, slots=True)
class OutboundDragPayload:
    """Describe a fully materialized native drag payload and preview."""

    items: tuple[OutboundMimeItem, ...] = ()
    urls: tuple[QUrl, ...] = ()
    text: str | None = None
    preview: QImage | None = None
    hotspot: QPoint | None = None

    def __post_init__(self) -> None:
        """Detach mutable Qt values and reject an empty payload."""
        urls = tuple(QUrl(url) for url in self.urls)
        preview = None if self.preview is None else QImage(self.preview)
        hotspot = None if self.hotspot is None else QPoint(self.hotspot)
        if not self.items and not urls and self.text is None and preview is None:
            raise ValueError("outbound drag payload must contain data")
        object.__setattr__(self, "urls", urls)
        object.__setattr__(self, "preview", preview)
        object.__setattr__(self, "hotspot", hotspot)


class DragCancellation(Protocol):
    """Cancel deferred host materialization when a drag becomes stale."""

    def cancel(self) -> None:
        """Request cancellation without blocking the GUI thread."""
        ...


DragCompletion = Callable[[OutboundDragPayload | None, BaseException | None], None]


class OutboundMimeProvider(Protocol):
    """Materialize host-selected MIME data synchronously or asynchronously."""

    def materialize(
        self,
        subject: DragSubject,
        complete: DragCompletion,
    ) -> DragCancellation | None:
        """Begin materialization and invoke ``complete`` exactly once."""
        ...


class _DragDelivery(QObject):
    """Marshal arbitrary provider completion threads onto the GUI thread."""

    completed = Signal(int, object, object)


class OutboundDragController(QObject):
    """Own one native drag lifecycle with stale-result and teardown safety."""

    failed = Signal(str)
    """Emit a host-facing message when payload materialization fails."""

    def __init__(
        self,
        parent: QWidget,
        *,
        execute: Callable[[QWidget, OutboundDragPayload], object] | None = None,
    ) -> None:
        """Bind native parent and optional test execution seam."""
        super().__init__(parent)
        self._widget = parent
        self._execute = execute or execute_outbound_drag
        self._delivery = _DragDelivery(self)
        self._delivery.completed.connect(
            self._complete,
            Qt.ConnectionType.QueuedConnection,
        )
        self._generation = 0
        self._pending: DragCancellation | None = None
        self._closed = False

    def start(
        self,
        subject: DragSubject,
        provider: OutboundMimeProvider,
    ) -> int:
        """Cancel stale work and request one host-selected drag payload."""
        if self._closed:
            raise RuntimeError("outbound drag controller is closed")
        if not isinstance(subject, DragSubject):
            raise TypeError("subject must be a DragSubject")
        self.cancel()
        self._generation += 1
        generation = self._generation

        def complete(
            payload: OutboundDragPayload | None,
            error: BaseException | None = None,
        ) -> None:
            """Marshal this generation's provider result onto the GUI thread."""
            self._delivery.completed.emit(generation, payload, error)

        self._pending = provider.materialize(subject, complete)
        return generation

    def cancel(self) -> bool:
        """Cancel pending materialization and invalidate any late result."""
        pending = self._pending
        if pending is None:
            return False
        self._pending = None
        self._generation += 1
        pending.cancel()
        return True

    def close(self) -> None:
        """Cancel pending work and reject future starts."""
        if self._closed:
            return
        self._closed = True
        self.cancel()

    def _complete(
        self,
        generation: int,
        payload: object,
        error: object,
    ) -> None:
        """Execute only the latest valid payload on the GUI thread."""
        if self._closed or generation != self._generation:
            return
        self._pending = None
        if isinstance(error, BaseException):
            self.failed.emit(str(error))
            return
        if not isinstance(payload, OutboundDragPayload):
            self.failed.emit("outbound MIME provider returned no payload")
            return
        self._execute(self._widget, payload)


def execute_outbound_drag(
    parent: QWidget,
    payload: OutboundDragPayload,
) -> Qt.DropAction:
    """Execute one fully materialized payload through Qt's native drag path."""
    mime_data = QMimeData()
    for item in payload.items:
        mime_data.setData(item.mime_type, QByteArray(item.data))
    if payload.urls:
        mime_data.setUrls(list(payload.urls))
    if payload.text is not None:
        mime_data.setText(payload.text)
    if payload.preview is not None and not payload.preview.isNull():
        mime_data.setImageData(payload.preview)
    drag = QDrag(parent)
    drag.setMimeData(mime_data)
    if payload.preview is not None and not payload.preview.isNull():
        drag.setPixmap(_preview_pixmap(parent, payload.preview))
    if payload.hotspot is not None:
        drag.setHotSpot(payload.hotspot)
    return drag.exec(Qt.DropAction.CopyAction)


def _preview_pixmap(parent: QWidget, image: QImage) -> QPixmap:
    """Scale a drag preview to a restrained fraction of the active display."""
    screen = parent.screen()
    size = QSize(240, 180)
    if screen is not None:
        available = screen.availableGeometry().size()
        size = QSize(
            max(1, round(available.width() * 0.15)),
            max(1, round(available.height() * 0.15)),
        )
    return QPixmap.fromImage(image).scaled(
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
