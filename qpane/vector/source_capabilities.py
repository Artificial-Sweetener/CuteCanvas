#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Focused metadata, vector-snapshot, and geometry capabilities."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QSize

from ..scene.source_references import LayerSourceReference
from .geometry import object_contains
from .model import VectorDocument
from .projection import VectorDocumentProjection, VectorPresentationSnapshot
from .source_reference import VectorDocumentReference
from .store import VectorAssetStore
from .text_layout import SemanticTextLayoutCache


class VectorSourceCapabilities:
    """Adapt vector document authority to focused scene consumers."""

    def __init__(
        self,
        assets: VectorAssetStore,
        projection: VectorDocumentProjection,
        text_layouts: SemanticTextLayoutCache,
    ) -> None:
        """Bind the authoritative vector document store."""
        self._assets = assets
        self._projection = projection
        self._text_layouts = text_layouts

    def source_size(self, source: LayerSourceReference) -> QSize | None:
        """Return the document canvas dimensions."""
        document = self._document(source)
        return (
            None
            if document is None
            else QSize(document.bounds.width, document.bounds.height)
        )

    def source_path(self, source: LayerSourceReference) -> Path | None:
        """Return no path because vector documents are composition resources."""
        return None

    def vector_document(
        self,
        source: LayerSourceReference,
    ) -> VectorPresentationSnapshot | None:
        """Return the current immutable document revision."""
        return (
            None
            if not isinstance(source, VectorDocumentReference)
            else self._projection.snapshot(source)
        )

    def contains(self, source: LayerSourceReference, point: QPointF) -> bool:
        """Hit test objects from top to bottom using authoritative geometry."""
        document = self._effective_document(source)
        return bool(
            document is not None
            and any(
                object_contains(item, point, self._text_layouts)
                for item in reversed(document.objects)
            )
        )

    def _document(self, source: LayerSourceReference) -> VectorDocument | None:
        """Resolve one exact typed source."""
        return (
            None
            if not isinstance(source, VectorDocumentReference)
            else self._assets.get(source.vector_id)
        )

    def _effective_document(
        self, source: LayerSourceReference
    ) -> VectorDocument | None:
        """Resolve presentation geometry for hit testing during transient edits."""
        return (
            None
            if not isinstance(source, VectorDocumentReference)
            else self._projection.document(source.vector_id)
        )
