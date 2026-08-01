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
"""Resolve viewport content selection without mutating document layer state."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace

from qpane.sdk.scene import LayerKind, SceneDescriptor

from ..composition.layers import CompositionLayerInstance
from ..composition.service import CompositionService
from ..document import (
    CanvasContentKind,
    CanvasDocument,
    CanvasRenderVariant,
    CanvasViewportSpec,
)
from ..masks.coverage_preview_source import MaskCoverageSourceReference
from .layer_assembly import CompositionLayerSceneAssembler


@dataclass(frozen=True, slots=True)
class ViewportSceneSelection:
    """Resolve one viewport specification into a filtered scene."""

    document: CanvasDocument
    compositions: CompositionService
    assembler: CompositionLayerSceneAssembler

    def composition_id(self, spec: CanvasViewportSpec) -> uuid.UUID:
        """Return the composition whose coordinate space presents the source."""
        self._validate_document(spec)
        composition_id = spec.source.composition_id
        if composition_id is not None:
            self.compositions.record(composition_id)
            return composition_id
        reference = spec.source.references[0]
        assert reference.resource_id is not None
        for candidate in self.compositions.composition_ids():
            if any(
                layer.source.resource_id == reference.resource_id
                for layer in self.compositions.layers.layers_for_composition(candidate)
            ):
                return candidate
        raise KeyError("viewport resource is not mounted by any composition")

    def assemble(
        self,
        spec: CanvasViewportSpec,
        document_scene: SceneDescriptor,
    ) -> SceneDescriptor:
        """Assemble exactly the selected instances in authoritative z-order."""
        composition_id = self.composition_id(spec)
        if document_scene.scene_id != composition_id:
            raise ValueError("document scene does not match viewport source")
        selected = self.assembler.assemble_instances(
            document_scene,
            self._instances(spec, composition_id),
        )
        if spec.render_variant is CanvasRenderVariant.MASK_COVERAGE:
            return self._mask_coverage_scene(selected)
        return selected

    def revision(self, spec: CanvasViewportSpec) -> tuple[object, ...]:
        """Return document and selection identity affecting the resolved scene."""
        current = tuple(
            self.document.resolve_content(reference).current
            for reference in spec.source.references
        )
        return (
            spec.viewport_id,
            spec.render_variant,
            current,
            self.assembler.revision(),
        )

    def _instances(
        self,
        spec: CanvasViewportSpec,
        composition_id: uuid.UUID,
    ) -> tuple[CompositionLayerInstance, ...]:
        """Return selected instances in composition order."""
        instances = self.compositions.layers.layers_for_composition(composition_id)
        references = spec.source.references
        kind = references[0].kind
        if kind is CanvasContentKind.COMPOSITION:
            return instances
        if kind is CanvasContentKind.LAYER:
            selected_ids = {reference.layer_id for reference in references}
            selected = tuple(
                instance for instance in instances if instance.layer_id in selected_ids
            )
            if len(selected) != len(selected_ids):
                raise KeyError("viewport layer no longer exists")
            return selected
        resource_id = references[0].resource_id
        selected = tuple(
            instance
            for instance in instances
            if instance.source.resource_id == resource_id
        )
        if not selected:
            raise KeyError("viewport resource is not mounted by the composition")
        return selected[:1]

    def _validate_document(self, spec: CanvasViewportSpec) -> None:
        """Reject sources owned by another document."""
        if spec.source.document_id != self.document.document_id:
            raise ValueError("viewport source belongs to another document")

    @staticmethod
    def _mask_coverage_scene(scene: SceneDescriptor) -> SceneDescriptor:
        """Normalize selected mask layers for neutral coverage rendering."""
        layers = tuple(
            replace(
                layer,
                source=MaskCoverageSourceReference(layer.source.resource_id),
                opacity=1.0,
            )
            for layer in scene.layers
            if layer.kind is LayerKind.MASK
        )
        if not layers:
            raise ValueError("mask-coverage viewport requires at least one mask layer")
        return replace(scene, layers=layers)


__all__ = ["ViewportSceneSelection"]
