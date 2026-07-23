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
"""Byte-bounded derived QPicture products for immutable vector revisions."""

from __future__ import annotations

import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtGui import QPainter, QPicture

from ..scene.raster import RasterBounds
from .drawing import draw_vector_document
from .model import VectorDocument
from .text_layout import SemanticTextLayoutCache


@dataclass(frozen=True, slots=True)
class VectorRenderProduct:
    """Retain one resolution-independent compiled drawing revision."""

    vector_id: uuid.UUID
    revision: int
    picture: QPicture
    retained_bytes: int


class VectorRenderCache:
    """Own least-recently-used compiled vector pictures under a byte budget."""

    def __init__(self, budget_bytes: int = 16 * 1024 * 1024) -> None:
        """Initialize an empty cache and strict retention ceiling."""
        self._budget_bytes = max(0, int(budget_bytes))
        self._usage_bytes = 0
        self._entries: OrderedDict[tuple[uuid.UUID, object], VectorRenderProduct] = (
            OrderedDict()
        )
        self._usage_changed: Callable[[int], None] | None = None
        self._empty_product: VectorRenderProduct | None = None
        self._text_layouts: SemanticTextLayoutCache | None = None

    @property
    def usage_bytes(self) -> int:
        """Return estimated retained QPicture bytes."""
        return self._usage_bytes

    @property
    def entry_count(self) -> int:
        """Return the number of retained document revisions."""
        return len(self._entries)

    def set_usage_changed(self, callback: Callable[[int], None] | None) -> None:
        """Install shared-cache usage publication."""
        self._usage_changed = callback

    def set_text_layouts(self, layouts: SemanticTextLayoutCache) -> None:
        """Install the vector domain's sole GUI-thread text derivative owner."""
        self._text_layouts = layouts

    def set_budget(self, budget_bytes: int) -> None:
        """Apply a strict cache budget and trim immediately."""
        self._budget_bytes = max(0, int(budget_bytes))
        self.trim_to(self._budget_bytes)

    def trim_to(self, target_bytes: int) -> None:
        """Evict oldest products until usage meets ``target_bytes``."""
        target = max(0, int(target_bytes))
        while self._entries and self._usage_bytes > target:
            _key, product = self._entries.popitem(last=False)
            self._usage_bytes -= product.retained_bytes
        self._report()

    def product(
        self,
        document: VectorDocument,
        revision_key: object | None = None,
    ) -> VectorRenderProduct:
        """Return or compile one immutable document revision."""
        key = (
            document.vector_id,
            document.revision if revision_key is None else revision_key,
        )
        product = self._entries.pop(key, None)
        if product is not None:
            self._entries[key] = product
            return product
        product = _compile_document(document, text_layouts=self._text_layouts)
        return self._admit(key, product)

    def empty_product(self, vector_id: uuid.UUID) -> VectorRenderProduct:
        """Return a reusable empty primitive while exact tiles refine."""
        product = self._empty_product
        if product is not None:
            return VectorRenderProduct(
                vector_id,
                product.revision,
                product.picture,
                product.retained_bytes,
            )
        document = VectorDocument(vector_id, RasterBounds(0, 0, 1, 1))
        product = _compile_document(document)
        self._empty_product = product
        return product

    def preview_products(
        self,
        document: VectorDocument,
        object_id: uuid.UUID,
        durable_revision: int,
    ) -> tuple[VectorRenderProduct, VectorRenderProduct, VectorRenderProduct]:
        """Return stable before/after products around one immediate preview object."""
        object_index = next(
            (
                index
                for index, item in enumerate(document.objects)
                if item.object_id == object_id
            ),
            -1,
        )
        if object_index < 0:
            empty = _compile_document(
                document,
                frozenset(),
                text_layouts=self._text_layouts,
            )
            return self.product(document), empty, empty
        before_ids = frozenset(
            item.object_id for item in document.objects[:object_index]
        )
        after_ids = frozenset(
            item.object_id for item in document.objects[object_index + 1 :]
        )
        before = self._subset_product(
            document,
            (durable_revision, object_id, "before"),
            before_ids,
        )
        active = _compile_document(
            document,
            frozenset((object_id,)),
            text_layouts=None,
        )
        after = self._subset_product(
            document,
            (durable_revision, object_id, "after"),
            after_ids,
        )
        return before, active, after

    def _subset_product(
        self,
        document: VectorDocument,
        revision_key: object,
        object_ids: frozenset[uuid.UUID],
    ) -> VectorRenderProduct:
        """Return or compile one stable ordered document segment."""
        key = (document.vector_id, revision_key)
        product = self._entries.pop(key, None)
        if product is not None:
            self._entries[key] = product
            return product
        return self._admit(
            key,
            _compile_document(
                document,
                object_ids,
                text_layouts=self._text_layouts,
            ),
        )

    def _admit(
        self,
        key: tuple[uuid.UUID, object],
        product: VectorRenderProduct,
    ) -> VectorRenderProduct:
        """Admit one derived product under the active byte ceiling."""
        if product.retained_bytes <= self._budget_bytes:
            self._entries[key] = product
            self._usage_bytes += product.retained_bytes
            self.trim_to(self._budget_bytes)
        return product

    def _report(self) -> None:
        """Publish exact retained usage after mutations."""
        if self._usage_changed is not None:
            self._usage_changed(self._usage_bytes)


def _compile_document(
    document: VectorDocument,
    object_ids: frozenset[uuid.UUID] | None = None,
    *,
    text_layouts: SemanticTextLayoutCache | None = None,
) -> VectorRenderProduct:
    """Compile semantic objects into a resolution-independent Qt picture."""
    picture = QPicture()
    if object_ids is not None and not object_ids:
        return VectorRenderProduct(
            document.vector_id,
            document.revision,
            picture,
            256,
        )
    painter = QPainter(picture)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        draw_vector_document(painter, document, object_ids, text_layouts)
    finally:
        painter.end()
    retained = max(256, int(picture.size()))
    return VectorRenderProduct(
        document.vector_id,
        document.revision,
        picture,
        retained,
    )
