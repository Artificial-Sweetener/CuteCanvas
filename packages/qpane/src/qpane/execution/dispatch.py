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
"""Define owner-context completion dispatch."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol


class CompletionDispatcher(Protocol):
    """Deliver one callback or acknowledge that delivery is impossible."""

    def dispatch(
        self,
        callback: Callable[[], None],
        *,
        discarded: Callable[[], None],
        reason: str,
    ) -> None:
        """Schedule callback delivery and invoke exactly one terminal branch."""


class InlineDispatcher:
    """Deliver callbacks synchronously for headless and deterministic owners."""

    def dispatch(
        self,
        callback: Callable[[], None],
        *,
        discarded: Callable[[], None],
        reason: str,
    ) -> None:
        """Invoke the callback immediately."""

        _ = discarded, reason
        callback()


__all__ = ["CompletionDispatcher", "InlineDispatcher"]
