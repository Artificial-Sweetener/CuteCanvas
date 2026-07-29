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
"""Synchronize document comparison targets with one persistent QPane catalog."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from qpane import QPane, RasterSource

from ..document import CanvasDocument, DocumentChange, DocumentChangeKind


class ComparisonCatalogSynchronizer:
    """Own catalog admission, replacement, removal, and document subscription."""

    def __init__(
        self,
        document: CanvasDocument,
        pane: QPane,
        title: Callable[[uuid.UUID], str],
    ) -> None:
        """Bind one native comparison catalog to durable document changes."""

        self._document = document
        self._pane = pane
        self._title = title
        self._cache_keys: dict[uuid.UUID, int] = {}
        self._revisions: dict[uuid.UUID, int] = {}
        self._unsubscribe = document.events.subscribe(self._document_changed)

    def ensure(self, composition_id: uuid.UUID, *, force: bool = False) -> None:
        """Admit one composition or refresh its changed embedded pixels."""

        image = self._document.embedded_image_for_composition(composition_id)
        cache_key = image.cacheKey()
        if composition_id not in self._cache_keys:
            self._pane.addImage(
                image,
                label=self._title(composition_id),
                source_id=composition_id,
                select=False,
            )
            self._cache_keys[composition_id] = cache_key
            self._revisions[composition_id] = 0
            return
        if not force and self._cache_keys[composition_id] == cache_key:
            return
        revision = self._revisions[composition_id] + 1
        self._pane.catalog().replace_source(
            RasterSource.from_image(
                image,
                source_id=composition_id,
                revision=revision,
            ),
            label=self._title(composition_id),
        )
        self._cache_keys[composition_id] = cache_key
        self._revisions[composition_id] = revision

    def close(self, _owner: object | None = None) -> None:
        """Detach document observation exactly once."""

        unsubscribe = self._unsubscribe
        self._unsubscribe = lambda: None
        unsubscribe()

    def _document_changed(self, change: DocumentChange) -> None:
        """Refresh catalog membership after relevant durable document changes."""

        if change.kind not in {
            DocumentChangeKind.LAYERS,
            DocumentChangeKind.RESOURCE,
        }:
            return
        available = set(self._document.composition_ids())
        for composition_id in tuple(self._cache_keys):
            if composition_id not in available:
                self._remove(composition_id)
        if change.kind is DocumentChangeKind.LAYERS:
            if (
                change.composition_id is not None
                and change.composition_id in self._cache_keys
                and change.composition_id in available
            ):
                self.ensure(change.composition_id)
            return
        if change.resource_id is None:
            return
        layers = self._document.resources.compositions.layers
        for composition_id in tuple(self._cache_keys):
            if composition_id not in available:
                continue
            if any(
                layer.source.resource_id == change.resource_id
                for layer in layers.layers_for_composition(composition_id)
            ):
                self.ensure(composition_id, force=True)

    def _remove(self, composition_id: uuid.UUID) -> None:
        """Remove one vanished composition from every catalog index."""

        self._pane.removeCatalogImage(composition_id)
        self._cache_keys.pop(composition_id, None)
        self._revisions.pop(composition_id, None)


__all__ = ["ComparisonCatalogSynchronizer"]
