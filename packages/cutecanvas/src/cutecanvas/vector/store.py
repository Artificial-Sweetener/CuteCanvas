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
"""Stable identity and immutable revision ownership for vector documents."""

from __future__ import annotations

import threading
import uuid

from qpane.sdk.scene import RasterBounds
from qpane.sdk.vector import VectorDocument


class VectorAssetStore:
    """Own every vector document payload by stable source identity."""

    def __init__(self) -> None:
        """Initialize an empty synchronized document collection."""
        self._documents: dict[uuid.UUID, VectorDocument] = {}
        self._lock = threading.RLock()
        self._revision = 0

    @property
    def revision(self) -> int:
        """Return the aggregate document-store revision."""
        with self._lock:
            return self._revision

    def create(self, bounds: RasterBounds) -> VectorDocument:
        """Create and retain one empty document."""
        document = VectorDocument(uuid.uuid4(), bounds)
        with self._lock:
            self._documents[document.vector_id] = document
            self._revision += 1
        return document

    def get(self, vector_id: uuid.UUID) -> VectorDocument | None:
        """Return the current immutable document revision."""
        with self._lock:
            return self._documents.get(vector_id)

    def replace(self, document: VectorDocument) -> bool:
        """Replace one document only when its stable identity exists."""
        with self._lock:
            if document.vector_id not in self._documents:
                return False
            self._documents[document.vector_id] = document
            self._revision += 1
            return True

    def restore(self, document: VectorDocument) -> None:
        """Install a validated document at its retained identity."""
        with self._lock:
            self._documents[document.vector_id] = document
            self._revision += 1

    def remove(self, vector_id: uuid.UUID) -> bool:
        """Release one unreachable document."""
        with self._lock:
            removed = self._documents.pop(vector_id, None) is not None
            if removed:
                self._revision += 1
            return removed

    def ids(self) -> tuple[uuid.UUID, ...]:
        """Return stable identities of all retained documents."""
        with self._lock:
            return tuple(self._documents)
