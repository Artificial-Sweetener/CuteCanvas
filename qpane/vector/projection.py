#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Transient vector presentation revisions over authoritative documents."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from .model import VectorDocument, VectorObject
from .source_reference import VectorDocumentReference
from .store import VectorAssetStore


@dataclass(frozen=True, slots=True)
class VectorPresentationSnapshot:
    """Carry one effective document and its derived-product identity."""

    document: VectorDocument
    revision_key: tuple[uuid.UUID, int, int]
    preview_object_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class _VectorObjectPreview:
    """Retain one immutable preview against its exact durable base."""

    base: VectorDocument
    document: VectorDocument
    object_id: uuid.UUID
    generation: int


class VectorDocumentProjection:
    """Own transient object previews without duplicating durable authority."""

    def __init__(self, assets: VectorAssetStore) -> None:
        """Bind the authoritative vector store."""
        self._assets = assets
        self._previews: dict[uuid.UUID, _VectorObjectPreview] = {}
        self._generation = 0

    @property
    def revision(self) -> tuple[int, int]:
        """Return durable and transient revisions affecting presentation."""
        return self._assets.revision, self._generation

    @property
    def source_revision(self) -> int:
        """Return a non-negative scalar revision for scene descriptors."""
        durable_revision = self._assets.revision
        total = durable_revision + self._generation
        return total * (total + 1) // 2 + self._generation

    def snapshot(
        self,
        source: VectorDocumentReference,
    ) -> VectorPresentationSnapshot | None:
        """Return the current effective document for one source reference."""
        durable = self._assets.get(source.vector_id)
        if durable is None:
            return None
        preview = self._previews.get(source.vector_id)
        if preview is None or preview.base != durable:
            return VectorPresentationSnapshot(
                durable,
                (durable.vector_id, durable.revision, 0),
            )
        return VectorPresentationSnapshot(
            preview.document,
            (durable.vector_id, durable.revision, preview.generation),
            preview.object_id,
        )

    def document(self, vector_id: uuid.UUID) -> VectorDocument | None:
        """Return the effective document by stable vector identity."""
        snapshot = self.snapshot(VectorDocumentReference(vector_id))
        return None if snapshot is None else snapshot.document

    def set_object_preview(
        self,
        vector_id: uuid.UUID,
        item: VectorObject,
    ) -> bool:
        """Present one replacement object over its unchanged durable document."""
        durable = self._assets.get(vector_id)
        if durable is None or durable.object(item.object_id) is None:
            return False
        document = durable.replace_object(item)
        current = self._previews.get(vector_id)
        if (
            current is not None
            and current.base == durable
            and current.document == document
        ):
            return False
        self._generation += 1
        self._previews[vector_id] = _VectorObjectPreview(
            durable,
            document,
            item.object_id,
            self._generation,
        )
        return True

    def set_document_preview(
        self,
        vector_id: uuid.UUID,
        document: VectorDocument,
        object_id: uuid.UUID,
    ) -> bool:
        """Present one controller-built document over its exact durable base."""
        durable = self._assets.get(vector_id)
        if (
            durable is None
            or document.vector_id != vector_id
            or document.object(object_id) is None
        ):
            return False
        current = self._previews.get(vector_id)
        if (
            current is not None
            and current.base == durable
            and current.document == document
            and current.object_id == object_id
        ):
            return False
        self._generation += 1
        self._previews[vector_id] = _VectorObjectPreview(
            durable,
            document,
            object_id,
            self._generation,
        )
        return True

    def clear(self, vector_id: uuid.UUID | None = None) -> bool:
        """Discard one or every transient preview revision."""
        if vector_id is None:
            changed = bool(self._previews)
            self._previews.clear()
        else:
            changed = self._previews.pop(vector_id, None) is not None
        if changed:
            self._generation += 1
        return changed
