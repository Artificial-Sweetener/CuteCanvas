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

"""Expose retry state in a diagnostics-friendly shape."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from types import SimpleNamespace


class RetryEntriesView:
    """Expose retry bookkeeping via the diagnostics snapshot protocol."""

    def __init__(
        self,
        category: str,
        entries_provider: Callable[[], MutableMapping],
    ) -> None:
        """Initialise the view around a retry category and entry source.

        Args:
            category: Name reported in diagnostics output.
            entries_provider: Callable returning the mutable retry map.
        """
        self._category = category
        self._entries_provider = entries_provider
        self.total_scheduled = 0

    def snapshot(self):
        """Expose counts mirroring the Diagnostics retry-controller surface.

        Returns:
            SimpleNamespace matching the RetryController snapshot contract.
        """
        entries = self._entries_provider()
        info = SimpleNamespace(
            active=len(entries),
            total_scheduled=self.total_scheduled,
        )
        return SimpleNamespace(categories={self._category: info})
