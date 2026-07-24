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
"""Durable vector owners shared by every view of a canvas document."""

from __future__ import annotations

from dataclasses import dataclass

from qpane.sdk.vector import SemanticTextLayoutCache

from ..composition import CompositionService
from ..resources import ProjectResourceKind, ProjectResourceStore
from ..resources.lifecycle import ProjectResourceLifecycleOwner
from .editing import VectorEditService
from .effects import VectorMaskController
from .projection import VectorDocumentProjection
from .store import VectorAssetStore


@dataclass(frozen=True, slots=True)
class VectorDocumentCore:
    """Group vector content, edits, projection, and semantic layout caches."""

    assets: VectorAssetStore
    edits: VectorEditService
    masks: VectorMaskController
    projection: VectorDocumentProjection
    text_layouts: SemanticTextLayoutCache

    @classmethod
    def create(
        cls,
        *,
        compositions: CompositionService,
        resources: ProjectResourceStore,
        lifecycle: ProjectResourceLifecycleOwner,
        changed,
    ) -> VectorDocumentCore:
        """Construct one vector-content graph for a headless document."""
        assets = VectorAssetStore(resources)
        projection = VectorDocumentProjection(assets)
        text_layouts = SemanticTextLayoutCache()
        lifecycle.register(ProjectResourceKind.VECTOR, assets.remove)
        edits = VectorEditService(
            assets=assets,
            edits=compositions.edit_controller,
            changed=changed,
        )
        masks = VectorMaskController(
            assets=assets,
            layers=compositions.layers,
            layer_edits=compositions.layer_edits,
        )
        return cls(assets, edits, masks, projection, text_layouts)
