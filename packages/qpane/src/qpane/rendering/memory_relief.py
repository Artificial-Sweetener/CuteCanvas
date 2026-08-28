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
"""Release unpublished render storage before derived shared caches."""

from __future__ import annotations

from collections.abc import Callable

from .storage_allocation import MemoryRelief
from .widget_surface import WidgetRenderSurface


class RenderMemoryRelief:
    """Coordinate deterministic relief without surrendering the front frame."""

    def __init__(
        self,
        surface: WidgetRenderSurface,
        downstream: MemoryRelief | None,
    ) -> None:
        """Capture protected presentation and optional derived-cache relief."""
        self._surface = surface
        self._downstream = downstream
        self._reclaimers: list[Callable[[], int]] = [
            surface.release_reclaimable_storage
        ]

    def add_reclaimer(self, reclaimer: Callable[[], int]) -> None:
        """Register one owner of recreateable or unpublished storage."""
        self._reclaimers.append(reclaimer)

    def __call__(self, requested_bytes: int, reason: str) -> int:
        """Release speculative native storage, then recreateable cache products."""
        released = 0
        for reclaimer in self._reclaimers:
            released += max(0, reclaimer())
        remaining = max(0, requested_bytes - released)
        if remaining > 0 and self._downstream is not None:
            released += self._downstream(remaining, reason)
        return released


__all__ = ["RenderMemoryRelief"]
