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
"""Define shared cache-coordination values without owning policy execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum


@dataclass(frozen=True, slots=True)
class CacheConsumerCallbacks:
    """Hooks that let the coordinator inspect and enforce cache usage."""

    get_usage: Callable[[], int]
    set_budget: Callable[[int], None]
    trim_to: Callable[[int], None]
    release_speculative: Callable[[str], int] | None = None


class CachePriority(IntEnum):
    """Eviction ordering where lower values trim before higher ones."""

    BACKGROUND_MODELS = 10
    BRUSH_TIPS = 15
    VECTOR_PRODUCTS = 18
    DERIVED_OVERLAYS = 20
    RASTER_PREVIEWS = 25
    TILES = 30
    PYRAMIDS = 40


@dataclass(slots=True)
class ConsumerRegistration:
    """Capture registration metadata plus optional budget hints."""

    consumer_id: str
    priority: CachePriority
    callbacks: CacheConsumerCallbacks
    weight: float = 1.0
    preferred_bytes: int | None = None
    override_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class TrimRecord:
    """Describe the last trim the coordinator asked a consumer to perform."""

    reason: str
    trimmed_bytes: int
    target_bytes: int
    timestamp: float


@dataclass(slots=True)
class ConsumerState:
    """Track live usage for a registered consumer and the last trim applied."""

    registration: ConsumerRegistration
    usage_bytes: int = 0
    last_trim: TrimRecord | None = None
    capacity_bytes: int | None = None

    @property
    def consumer_id(self) -> str:
        """Expose the registered consumer identifier for diagnostics."""
        return self.registration.consumer_id


__all__ = [
    "CacheConsumerCallbacks",
    "CachePriority",
    "ConsumerRegistration",
    "ConsumerState",
    "TrimRecord",
]
