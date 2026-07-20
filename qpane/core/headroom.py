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

"""Background system-memory observation for automatic cache budgeting."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtCore import QObject, QRunnable, Signal

from ..concurrency import BaseWorker

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SystemHeadroomSample:
    """Immutable physical and swap-memory observation."""

    available_bytes: int
    total_bytes: int
    swap_total_bytes: int | None = None
    swap_free_bytes: int | None = None

    def diagnostic_snapshot(self) -> dict[str, object]:
        """Return the cache-coordinator diagnostic representation."""
        snapshot: dict[str, object] = {
            "available_bytes": max(0, self.available_bytes),
            "total_bytes": max(0, self.total_bytes),
        }
        if self.swap_total_bytes is not None:
            snapshot["swap_total_bytes"] = max(0, self.swap_total_bytes)
        if self.swap_free_bytes is not None:
            snapshot["swap_free_bytes"] = max(0, self.swap_free_bytes)
        return snapshot


class SystemHeadroomWorker(QObject, QRunnable, BaseWorker):
    """Sample optional system-memory APIs away from the GUI thread."""

    finished = Signal(object)
    error = Signal(object)

    def __init__(self, psutil_module: object | None = None) -> None:
        """Capture an optional provider used by deterministic tests."""
        QObject.__init__(self)
        QRunnable.__init__(self)
        BaseWorker.__init__(self, logger=logger)
        self.psutil_module = psutil_module
        self.sample: SystemHeadroomSample | None = None
        self.error_message: str | None = None

    def run(self) -> None:
        """Observe memory once and publish one terminal result."""
        try:
            provider = self.psutil_module
            if provider is None:
                import psutil  # type: ignore

                provider = psutil
                self.psutil_module = provider
            if self.is_cancelled:
                self.emit_finished(False, payload=self)
                return
            memory = provider.virtual_memory()  # type: ignore[attr-defined]
            swap_total: int | None = None
            swap_free: int | None = None
            try:
                swap = provider.swap_memory()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 - optional system diagnostic
                swap = None
            if swap is not None:
                swap_total = int(swap.total)
                swap_free = int(swap.free)
            self.sample = SystemHeadroomSample(
                available_bytes=int(memory.available),
                total_bytes=int(memory.total),
                swap_total_bytes=swap_total,
                swap_free_bytes=swap_free,
            )
        except BaseException as exc:  # noqa: BLE001 - optional system boundary
            self.error_message = str(exc)
        self.emit_finished(
            self.sample is not None
            and self.error_message is None
            and not self.is_cancelled,
            payload=self,
        )
