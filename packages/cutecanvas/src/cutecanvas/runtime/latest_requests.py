#    CuteCanvas - High-performance layered image editor
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
"""Coordinate replaceable document work across every mounted view."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Hashable
from threading import Lock

DocumentRequestKey = tuple[str, Hashable]


class DocumentLatestRequestRegistry:
    """Own one current replaceable request for each document operation key."""

    def __init__(self) -> None:
        """Create an empty thread-safe request registry."""
        self._entries: dict[
            DocumentRequestKey,
            tuple[uuid.UUID, Callable[[str], None]],
        ] = {}
        self._closed = False
        self._lock = Lock()

    def claim(
        self,
        key: DocumentRequestKey,
        request_id: uuid.UUID,
        cancel: Callable[[str], None],
    ) -> bool:
        """Claim ``key`` and cancel the prior request outside the registry lock."""
        with self._lock:
            if self._closed:
                return False
            previous = self._entries.get(key)
            self._entries[key] = (request_id, cancel)
        if previous is not None and previous[0] != request_id:
            previous[1]("replaced by a newer document request")
        return True

    def is_current(
        self,
        key: DocumentRequestKey,
        request_id: uuid.UUID,
    ) -> bool:
        """Return whether ``request_id`` still owns ``key``."""
        with self._lock:
            entry = self._entries.get(key)
            return entry is not None and entry[0] == request_id

    def current_request_id(
        self,
        key: DocumentRequestKey,
    ) -> uuid.UUID | None:
        """Return the current request identity for ``key`` when present."""
        with self._lock:
            entry = self._entries.get(key)
            return None if entry is None else entry[0]

    def release(
        self,
        key: DocumentRequestKey,
        request_id: uuid.UUID,
    ) -> None:
        """Release ``key`` only when it is still owned by ``request_id``."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry[0] == request_id:
                self._entries.pop(key, None)

    def cancel(self, key: DocumentRequestKey, *, reason: str) -> bool:
        """Release and cancel the current request for ``key`` when present."""
        with self._lock:
            entry = self._entries.pop(key, None)
        if entry is None:
            return False
        entry[1](reason)
        return True

    def cancel_request(
        self,
        key: DocumentRequestKey,
        request_id: uuid.UUID,
        *,
        reason: str,
    ) -> bool:
        """Cancel ``request_id`` only while it still owns ``key``."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry[0] != request_id:
                return False
            self._entries.pop(key, None)
        entry[1](reason)
        return True

    def close(self) -> None:
        """Reject future claims and cancel every current document request."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            entries = tuple(self._entries.values())
            self._entries.clear()
        for _request_id, cancel in entries:
            cancel("document runtime closed")


__all__ = ["DocumentLatestRequestRegistry", "DocumentRequestKey"]
