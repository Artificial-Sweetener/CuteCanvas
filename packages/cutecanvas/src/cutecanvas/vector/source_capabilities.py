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
"""Focused metadata, vector-snapshot, and geometry capabilities."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize
from qpane.sdk.scene import LayerSourceReference, RasterBounds
from qpane.sdk.vector import (
    SemanticTextLayoutCache,
    VectorDocument,
    VectorPresentationSnapshot,
    object_contains,
    painted_document_path,
)

from .projection import VectorDocumentProjection
from .source_reference import VectorDocumentReference
from .store import VectorAssetStore


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

    def content_bounds(self, source: LayerSourceReference) -> QRectF | None:
        """Return exact painted vector geometry bounds without rasterization."""
        document = self._effective_document(source)
        if document is None or not document.objects:
            return None
        rectangle = painted_document_path(
            document, text_layouts=self._text_layouts
        ).boundingRect()
        return None if rectangle.isEmpty() else QRectF(rectangle)

    def storage_bounds(self, source: LayerSourceReference) -> QRectF | None:
        """Return the vector document's finite canvas envelope."""
        document = self._document(source)
        return None if document is None else _rectf(document.bounds)

    def authored_bounds(self, source: LayerSourceReference) -> QRectF | None:
        """Return semantic vector geometry without rasterizing it."""
        return self.content_bounds(source)

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


def _rectf(bounds: RasterBounds) -> QRectF:
    """Return continuous geometry for one integer document envelope."""
    return QRectF(bounds.x, bounds.y, bounds.width, bounds.height)
