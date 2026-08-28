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
"""Protect completed presentation when recoverable frame work is rejected."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

FramePlan = TypeVar("FramePlan")


def attempt_retained_frame_update(
    plan: FramePlan,
    *,
    ensure_storage: Callable[[], None],
    paint: Callable[[FramePlan], object],
) -> bool:
    """Attempt one frame while translating memory contention into retention."""
    try:
        ensure_storage()
        paint(plan)
    except MemoryError as error:
        logger.warning(
            "Retaining last completed frame after memory contention | "
            "operation=render_frame | reason=%s",
            error,
            extra={
                "memory_pressure": {
                    "operation": "render_frame",
                    "reason": str(error),
                }
            },
        )
        return False
    return True


__all__ = ["attempt_retained_frame_update"]
