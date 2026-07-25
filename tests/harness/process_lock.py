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
"""Cross-process isolation for strict performance probes."""

from __future__ import annotations

import os
import time
from pathlib import Path
from types import TracebackType
from typing import BinaryIO

from typing_extensions import Self


class InterprocessPerformanceLock:
    """Serialize hardware-sensitive probes across pytest workers."""

    def __init__(self, path: Path) -> None:
        """Create a lock backed by one shared temporary file."""
        self._path = Path(path)
        self._stream: BinaryIO | None = None

    def __enter__(self) -> Self:
        """Acquire the process-wide benchmark slot."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        stream = self._path.open("a+b")
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        self._stream = stream
        self._acquire(stream.fileno())
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Release the benchmark slot even when a probe fails."""
        del exc_type, exc_value, traceback
        stream = self._stream
        self._stream = None
        if stream is None:
            return
        try:
            self._release(stream.fileno())
        finally:
            stream.close()

    @staticmethod
    def _acquire(file_descriptor: int) -> None:
        """Block until the platform file lock becomes available."""
        if os.name == "nt":
            import msvcrt

            while True:
                try:
                    msvcrt.locking(file_descriptor, msvcrt.LK_NBLCK, 1)
                    return
                except OSError:
                    time.sleep(0.01)
        else:
            import fcntl

            fcntl.flock(file_descriptor, fcntl.LOCK_EX)

    @staticmethod
    def _release(file_descriptor: int) -> None:
        """Release the platform file lock."""
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(file_descriptor, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(file_descriptor, fcntl.LOCK_UN)
