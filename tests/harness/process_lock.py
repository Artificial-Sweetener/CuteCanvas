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
"""Cross-process shared/exclusive isolation for strict performance probes."""

from __future__ import annotations

import os
import time
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, BinaryIO

from typing_extensions import Self

if TYPE_CHECKING:
    import pytest


def interactive_performance_isolation(
    request: pytest.FixtureRequest,
) -> InterprocessPerformanceIsolation:
    """Build the shared admission policy for one collected test."""
    worker_slot, slot_count = performance_worker_slots(request)
    exclusive = request.node.get_closest_marker("interactive_performance") is not None
    return InterprocessPerformanceIsolation(
        Path.cwd() / ".pytest-tmp",
        worker_slot=worker_slot,
        worker_count=slot_count,
        exclusive=exclusive,
    )


def performance_worker_slots(
    request: pytest.FixtureRequest,
) -> tuple[int, int]:
    """Return this worker slot and capacity including allowed replacements."""
    worker_input = getattr(request.config, "workerinput", None)
    if worker_input is None:
        return 0, 1
    worker_id = str(worker_input["workerid"])
    worker_slot = int(worker_id.removeprefix("gw"))
    worker_count = int(worker_input["workercount"])
    configured_restarts = getattr(request.config.option, "maxworkerrestart", None)
    restart_capacity = (
        worker_count * 4
        if configured_restarts is None
        else max(0, int(configured_restarts))
    )
    return worker_slot, worker_count + restart_capacity


class InterprocessPerformanceIsolation:
    """Let ordinary workers run together while performance probes run alone."""

    def __init__(
        self,
        root: Path,
        *,
        worker_slot: int,
        worker_count: int,
        exclusive: bool,
    ) -> None:
        """Bind one worker to the shared benchmark admission protocol."""
        if worker_count <= 0:
            raise ValueError("worker_count must be positive")
        if not 0 <= worker_slot < worker_count:
            raise ValueError("worker_slot must identify one worker")
        root = Path(root)
        self._admission_path = root / "interactive-performance-admission.lock"
        self._activity_path = root / "interactive-performance-activity.lock"
        self._worker_slot = worker_slot
        self._worker_count = worker_count
        self._exclusive = exclusive
        self._admission: _InterprocessByteLock | None = None
        self._activity: list[_InterprocessByteLock] = []

    def __enter__(self) -> Self:
        """Admit one parallel test or drain all workers for a strict probe."""
        admission = _InterprocessByteLock(self._admission_path, byte_offset=0)
        admission.__enter__()
        if self._exclusive:
            self._admission = admission
            try:
                for slot in range(self._worker_count):
                    activity = _InterprocessByteLock(
                        self._activity_path,
                        byte_offset=slot,
                    )
                    activity.__enter__()
                    self._activity.append(activity)
            except BaseException:
                self.__exit__(None, None, None)
                raise
            return self
        activity = _InterprocessByteLock(
            self._activity_path,
            byte_offset=self._worker_slot,
        )
        try:
            activity.__enter__()
            self._activity.append(activity)
        finally:
            admission.__exit__(None, None, None)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Release worker activity and reopen performance admission."""
        del exc_type, exc_value, traceback
        while self._activity:
            self._activity.pop().__exit__(None, None, None)
        admission = self._admission
        self._admission = None
        if admission is not None:
            admission.__exit__(None, None, None)


class _InterprocessByteLock:
    """Own one byte-range lock in a shared coordination file."""

    def __init__(self, path: Path, *, byte_offset: int) -> None:
        """Configure one nonnegative byte as the lock identity."""
        if byte_offset < 0:
            raise ValueError("byte_offset must be nonnegative")
        self._path = Path(path)
        self._byte_offset = byte_offset
        self._stream: BinaryIO | None = None

    def __enter__(self) -> Self:
        """Acquire the configured byte across processes."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        stream = self._path.open("a+b")
        stream.seek(0, os.SEEK_END)
        missing = self._byte_offset + 1 - stream.tell()
        if missing > 0:
            stream.write(b"\0" * missing)
            stream.flush()
        stream.seek(self._byte_offset)
        self._stream = stream
        self._acquire(stream.fileno(), self._byte_offset)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Release the byte even when the protected operation fails."""
        del exc_type, exc_value, traceback
        stream = self._stream
        self._stream = None
        if stream is None:
            return
        try:
            self._release(stream.fileno(), self._byte_offset)
        finally:
            stream.close()

    @staticmethod
    def _acquire(file_descriptor: int, byte_offset: int) -> None:
        """Block until the selected cross-platform byte becomes available."""
        if os.name == "nt":
            import msvcrt

            while True:
                try:
                    os.lseek(file_descriptor, byte_offset, os.SEEK_SET)
                    msvcrt.locking(file_descriptor, msvcrt.LK_NBLCK, 1)
                    return
                except OSError:
                    time.sleep(0.01)
        else:
            import fcntl

            fcntl.lockf(file_descriptor, fcntl.LOCK_EX, 1, byte_offset)

    @staticmethod
    def _release(file_descriptor: int, byte_offset: int) -> None:
        """Release the selected cross-platform byte."""
        if os.name == "nt":
            import msvcrt

            os.lseek(file_descriptor, byte_offset, os.SEEK_SET)
            msvcrt.locking(file_descriptor, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.lockf(file_descriptor, fcntl.LOCK_UN, 1, byte_offset)
