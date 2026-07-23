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
"""Final-release routing for vector document resources."""

from __future__ import annotations

from qpane.sdk.scene import LayerSourceReference

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
