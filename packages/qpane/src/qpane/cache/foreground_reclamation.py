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
"""Reclaim recreateable cache products for foreground native allocations."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .coordinator_model import ConsumerState

logger = logging.getLogger(__name__)

TrimConsumer = Callable[[ConsumerState, int, str], int]


@dataclass(frozen=True, slots=True)
class ForegroundReclamation:
    """Describe synchronous derived-cache relief and its diagnostic events."""

    freed_bytes: int
    events: tuple[dict[str, object], ...]


def reclaim_for_foreground_allocation(
    states: Iterable[ConsumerState],
    *,
    requested_bytes: int,
    reason: str,
    trim_consumer: TrimConsumer,
) -> ForegroundReclamation:
    """Release recreateable products in semantic priority order."""
    remaining = max(0, int(requested_bytes))
    if remaining == 0:
        return ForegroundReclamation(0, ())
    candidates = tuple(states)
    usage_before = sum(state.usage_bytes for state in candidates)
    events: list[dict[str, object]] = []
    ordered = sorted(
        candidates,
        key=lambda state: (
            state.registration.priority,
            -state.usage_bytes,
            state.consumer_id,
        ),
    )
    for state in ordered:
        release_speculative = state.registration.callbacks.release_speculative
        if release_speculative is None:
            continue
        try:
            released_work = max(0, int(release_speculative(reason)))
        except Exception:
            logger.exception(
                "Speculative cache work cancellation failed | consumer=%s | reason=%s",
                state.consumer_id,
                reason,
            )
            continue
        if released_work:
            events.append(
                {
                    "consumer": state.consumer_id,
                    "priority": int(state.registration.priority),
                    "released_speculative_work": released_work,
                }
            )
    for state in ordered:
        if remaining <= 0:
            break
        target = max(0, state.usage_bytes - remaining)
        freed = trim_consumer(state, target, f"allocation:{reason}")
        if freed <= 0:
            continue
        remaining = max(0, remaining - freed)
        events.append(
            {
                "consumer": state.consumer_id,
                "priority": int(state.registration.priority),
                "freed_bytes": freed,
                "usage_after": state.usage_bytes,
            }
        )
    freed_total = max(0, usage_before - sum(state.usage_bytes for state in candidates))
    logger.warning(
        "Foreground allocation reclaimed derived caches | reason=%s | "
        "requested_bytes=%d | freed_bytes=%d | events=%s",
        reason,
        requested_bytes,
        freed_total,
        events,
        extra={
            "memory_pressure": {
                "reason": reason,
                "requested_bytes": requested_bytes,
                "freed_bytes": freed_total,
                "events": events,
            }
        },
    )
    return ForegroundReclamation(freed_total, tuple(events))


__all__ = ["ForegroundReclamation", "reclaim_for_foreground_allocation"]
