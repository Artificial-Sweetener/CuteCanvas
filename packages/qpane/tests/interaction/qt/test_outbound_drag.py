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
"""Verify generalized deferred MIME drag lifecycle behavior."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QWidget

from qpane.sdk.ui import (
    DragSubject,
    OutboundDragController,
    OutboundDragPayload,
    OutboundMimeItem,
)


@dataclass
class _Cancellation:
    """Record whether one pending provider request was cancelled."""

    cancelled: bool = False

    def cancel(self) -> None:
        """Record cancellation without blocking."""
        self.cancelled = True


class _Provider:
    """Capture completions so tests can deliver out-of-order results."""

    def __init__(self) -> None:
        """Initialize pending callback and cancellation lists."""
        self.completions = []
        self.cancellations = []

    def materialize(self, subject, complete):
        """Retain one request instead of completing it synchronously."""
        self.completions.append((subject, complete))
        cancellation = _Cancellation()
        self.cancellations.append(cancellation)
        return cancellation


def _payload(label: str) -> OutboundDragPayload:
    """Return a multi-format payload with host-controlled companion URL."""
    return OutboundDragPayload(
        items=(OutboundMimeItem("application/x-example", label.encode()),),
        urls=(QUrl.fromLocalFile(f"C:/{label}.jpg"),),
        text=label,
    )


def test_controller_ignores_stale_completion_after_new_request(qapp) -> None:
    """Late materialization cannot start the wrong host drag."""
    parent = QWidget()
    provider = _Provider()
    executed = []
    controller = OutboundDragController(
        parent,
        execute=lambda _parent, payload: executed.append(payload),
    )
    try:
        controller.start(DragSubject("first"), provider)
        controller.start(DragSubject("second"), provider)
        assert provider.cancellations[0].cancelled

        provider.completions[0][1](_payload("stale"), None)
        provider.completions[1][1](_payload("current"), None)
        qapp.processEvents()

        assert [payload.text for payload in executed] == ["current"]
    finally:
        controller.close()
        parent.close()


def test_controller_cancels_pending_materialization_on_close(qapp) -> None:
    """Teardown rejects deferred completion without touching a dead widget."""
    parent = QWidget()
    provider = _Provider()
    executed = []
    controller = OutboundDragController(
        parent,
        execute=lambda _parent, payload: executed.append(payload),
    )
    controller.start(DragSubject("pending"), provider)
    controller.close()
    provider.completions[0][1](_payload("late"), None)
    qapp.processEvents()

    assert provider.cancellations[0].cancelled
    assert executed == []
    parent.close()
