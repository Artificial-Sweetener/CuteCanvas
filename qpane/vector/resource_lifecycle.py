#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Final-release routing for vector document resources."""

from __future__ import annotations

from ..scene.source_references import LayerSourceReference
from .source_reference import VectorDocumentReference
from .store import VectorAssetStore


class VectorResourceLifecycleOwner:
    """Release vector payloads after all composition leases disappear."""

    source_type = VectorDocumentReference

    def __init__(self, assets: VectorAssetStore) -> None:
        """Bind the authoritative vector store."""
        self._assets = assets

    def release_unreachable(self, source: LayerSourceReference) -> None:
        """Delete the exact vector document when it becomes unreachable."""
        if isinstance(source, VectorDocumentReference):
            self._assets.remove(source.vector_id)
