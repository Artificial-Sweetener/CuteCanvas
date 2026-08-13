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
"""Prove receiver teardown cannot overlap Qt callback publication."""

from __future__ import annotations

import threading
from types import TracebackType

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QApplication

from qpane.execution.qt_dispatch import QtOwnerDispatcher


class _ObservedLock:
    """Record whether one designated caller encounters an acquired lock."""

    def __init__(self) -> None:
        """Create an unlocked lifecycle probe."""
        self._lock = threading.Lock()
        self.observed_thread_id: int | None = None
        self.observation_ready = threading.Event()
        self.observed_held_state: bool | None = None

    def __enter__(self) -> None:
        """Record the lock state immediately before the designated acquire."""
        if threading.get_ident() == self.observed_thread_id:
            self.observed_held_state = self._lock.locked()
            self.observation_ready.set()
        self._lock.acquire()

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Release the observed lock."""
        del exception_type, exception, traceback
        self._lock.release()


def test_dispatch_publication_and_close_are_one_atomic_lifecycle_transition(
    qapp: QApplication,
) -> None:
    """Receiver close must wait until an in-flight Qt signal publish completes."""
    receiver = QObject()
    dispatcher = QtOwnerDispatcher(receiver)
    lifecycle_lock = _ObservedLock()
    dispatcher._lock = lifecycle_lock
    publication_entered = threading.Event()
    release_publication = threading.Event()
    delivered: list[str] = []
    discarded: list[str] = []

    def block_publication(_dispatch_id: int) -> None:
        """Hold signal emission while another thread starts close."""
        publication_entered.set()
        assert release_publication.wait(timeout=1.0)

    dispatcher._requested.connect(
        block_publication,
        Qt.ConnectionType.DirectConnection,
    )
    publish_thread = threading.Thread(
        target=lambda: dispatcher.dispatch(
            lambda: delivered.append("delivered"),
            discarded=lambda: discarded.append("discarded"),
            reason="lifecycle-invariant",
        )
    )

    def close_dispatcher() -> None:
        """Mark this thread as the observed lifecycle closer."""
        lifecycle_lock.observed_thread_id = threading.get_ident()
        dispatcher.close()

    close_thread = threading.Thread(target=close_dispatcher)
    publish_thread.start()
    assert publication_entered.wait(timeout=1.0)
    close_thread.start()
    assert lifecycle_lock.observation_ready.wait(timeout=1.0)

    assert lifecycle_lock.observed_held_state is True
    release_publication.set()
    publish_thread.join(timeout=1.0)
    close_thread.join(timeout=1.0)
    assert not publish_thread.is_alive()
    assert not close_thread.is_alive()
    qapp.processEvents()
    assert delivered == []
    assert discarded == ["discarded"]

    receiver.deleteLater()
    qapp.processEvents()
