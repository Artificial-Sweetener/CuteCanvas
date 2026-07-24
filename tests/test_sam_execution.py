#    QPane + CuteCanvas - High-performance PySide6 rendering and editing
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

"""Tests for SAM's persistent native-model execution lane."""

from __future__ import annotations

import threading

from cutecanvas.sam.execution import build_sam_executor
from PySide6.QtCore import QRunnable
from qpane.sdk.concurrency import BaseWorker


class _ThreadIdentityWorker(QRunnable, BaseWorker):
    """Record the native thread used by one executor task."""

    def __init__(
        self,
        identities: list[int],
        finished: threading.Event,
        expected_count: int,
    ) -> None:
        """Capture shared result state."""
        QRunnable.__init__(self)
        BaseWorker.__init__(self)
        self._identities = identities
        self._finished = finished
        self._expected_count = expected_count

    def run(self) -> None:
        """Record thread identity and report completion."""
        self._identities.append(threading.get_ident())
        if len(self._identities) == self._expected_count:
            self._finished.set()
        self.emit_finished(True)


def test_sam_executor_reuses_one_persistent_native_thread() -> None:
    """Serialized model jobs must not migrate between Qt pool threads."""
    executor = build_sam_executor(
        {
            "max_workers": 4,
            "max_pending_total": 8,
            "pending_limits": {"sam": 4},
        },
        device="cpu",
    )
    identities: list[int] = []
    finished = threading.Event()

    executor.submit(
        _ThreadIdentityWorker(identities, finished, 3),
        category="sam",
        device="cpu",
    )
    executor.submit(
        _ThreadIdentityWorker(identities, finished, 3),
        category="sam",
        device="cpu",
    )
    executor.submit(
        _ThreadIdentityWorker(identities, finished, 3),
        category="sam",
        device="cpu",
    )

    assert finished.wait(timeout=5)
    executor.shutdown()
    assert len(identities) == 3
    assert len(set(identities)) == 1
