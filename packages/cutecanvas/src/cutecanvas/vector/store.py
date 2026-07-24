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
from dataclasses import replace

from qpane.sdk.scene import RasterBounds
from qpane.sdk.vector import VectorDocument

from ..resources import ProjectResourceKind, ProjectResourceStore


class VectorAssetStore:
    """Own every vector document payload by stable source identity."""

    def __init__(self, resources: ProjectResourceStore) -> None:
        """Initialize vector payloads against the project resource graph."""
        self._resources = resources
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
        self._resources.create(
            ProjectResourceKind.VECTOR,
            editable=True,
            resource_id=document.vector_id,
        )
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
            self._resources.touch(document.vector_id)
            return True

    def restore(self, document: VectorDocument) -> None:
        """Install a validated document at its retained identity."""
        record = self._resources.get(document.vector_id)
        if record is None:
            self._resources.create(
                ProjectResourceKind.VECTOR,
                editable=True,
                resource_id=document.vector_id,
            )
        elif record.kind is not ProjectResourceKind.VECTOR:
            raise ValueError("vector identity belongs to another resource kind")
        with self._lock:
            self._documents[document.vector_id] = document
            self._revision += 1

    def remove(self, vector_id: uuid.UUID) -> bool:
        """Release one unreachable document."""
        if self._resources.get(vector_id) is not None:
            self._resources.remove(vector_id)
        with self._lock:
            removed = self._documents.pop(vector_id, None) is not None
            if removed:
                self._revision += 1
            return removed

    def fork(self, vector_id: uuid.UUID) -> uuid.UUID | None:
        """Clone one vector document into an independent project resource."""
        with self._lock:
            document = self._documents.get(vector_id)
            if document is None:
                return None
            fork_id = uuid.uuid4()
            forked = replace(document, vector_id=fork_id, revision=0)
            self._resources.create(
                ProjectResourceKind.VECTOR,
                editable=True,
                resource_id=fork_id,
            )
            self._documents[fork_id] = forked
            self._revision += 1
            return fork_id

    def ids(self) -> tuple[uuid.UUID, ...]:
        """Return stable identities of all retained documents."""
        with self._lock:
            return tuple(self._documents)
