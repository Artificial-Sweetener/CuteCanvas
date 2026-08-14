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
"""Install the vector domain through focused composition capabilities."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QRect, QRectF

from qpane.sdk.cache import CacheRegistry
from qpane.sdk.execution import ExecutionScope
from qpane.sdk.rendering import SceneCoordinateSystem
from qpane.sdk.scene import (
    LayerEffectRenderRegistry,
    LayerSourceCapabilities,
    SceneDescriptor,
)
from qpane.sdk.vector import SemanticTextLayoutCache

from ..composition import CompositionService
from ..raster.assets import EditableRasterAssetStore
from ..resources import ProjectResourceKind, ProjectResourceStore
from ..resources.descriptor_factory import ProjectResourceLayerDescriptorFactory
from ..resources.lifecycle import ProjectResourceLifecycleOwner
from ..resources.source_capabilities import ProjectResourceSourceCapabilities
from ..runtime.latest_requests import DocumentLatestRequestRegistry
from ..scene.layer_assembly import CompositionLayerSceneAssembler
from ..scene.layer_selection import SceneLayerSelectionController
from ..scene.mutations import SceneMutationCoordinator
from ..scene.source_capabilities import EditorSourceCapabilities
from ..selection import PixelSelectionService
from .conversion import VectorConversionCompletion, VectorConversionService
from .descriptor_factory import VectorLayerDescriptorFactory
from .document_core import VectorDocumentCore
from .editing import VectorEditService
from .effects import VectorMaskController, VectorMaskEffect, VectorMaskRenderOwner
from .interaction import VectorInteractionController
from .layers import VectorLayerController, VectorSceneMutationOwner
from .mask_cache import VectorMaskPathCache
from .node_edit import VectorNodeEditController
from .projection import VectorDocumentProjection
from .selection import VectorObjectSelectionController
from .source_capabilities import VectorSourceCapabilities
from .store import VectorAssetStore
from .targets import VectorAuthoringTargetResolver
from .text_edit import VectorTextEditController


@dataclass(frozen=True, slots=True)
class VectorDomainComponents:
    """Expose the authoritative collaborators installed for vector editing."""

    assets: VectorAssetStore
    layers: VectorLayerController
    edits: VectorEditService
    selection: VectorObjectSelectionController
    interaction: VectorInteractionController
    conversions: VectorConversionService
    masks: VectorMaskController
    targets: VectorAuthoringTargetResolver
    projection: VectorDocumentProjection
    nodes: VectorNodeEditController
    texts: VectorTextEditController
    text_layouts: SemanticTextLayoutCache


class VectorDomainInstaller:
    """Own vector-domain construction and its cross-domain registrations."""

    def install(
        self,
        *,
        compositions: CompositionService,
        document: VectorDocumentCore,
        resources: ProjectResourceStore,
        resource_descriptors: ProjectResourceLayerDescriptorFactory,
        resource_capabilities: ProjectResourceSourceCapabilities,
        resource_lifecycle: ProjectResourceLifecycleOwner,
        layer_assembler: CompositionLayerSceneAssembler,
        source_capabilities: LayerSourceCapabilities,
        editor_source_capabilities: EditorSourceCapabilities,
        scene_mutations: SceneMutationCoordinator,
        current_composition_id: Callable[[], uuid.UUID | None],
        current_history_scope_id: Callable[[], uuid.UUID | None],
        changed: Callable[[QRect | QRectF | None], None],
        selection_changed: Callable[[], None],
        node_selection_changed: Callable[[], None],
        text_edit_changed: Callable[[], None],
        options_changed: Callable[[], None],
        layer_selection: SceneLayerSelectionController,
        current_scene: Callable[[], SceneDescriptor | None],
        coordinates: SceneCoordinateSystem,
        raster_assets: EditableRasterAssetStore,
        pixel_selection: PixelSelectionService,
        execution_scope: ExecutionScope,
        latest_requests: DocumentLatestRequestRegistry,
        conversion_completed: Callable[[VectorConversionCompletion], None],
        layer_effects: LayerEffectRenderRegistry,
        cache_registry: CacheRegistry | None,
    ) -> VectorDomainComponents:
        """Create vector owners and register each focused external capability."""
        assets = document.assets
        projection = document.projection
        text_layouts = document.text_layouts
        if cache_registry is not None:
            cache_registry.attach_text_layout_cache(text_layouts)
        layers = VectorLayerController(
            assets=assets,
            layers=compositions.layers,
            layer_edits=compositions.layer_edits,
            current_composition_id=current_composition_id,
            current_history_scope_id=current_history_scope_id,
        )
        resource_descriptors.register(
            ProjectResourceKind.VECTOR,
            VectorLayerDescriptorFactory(projection),
        )
        capabilities = VectorSourceCapabilities(assets, projection, text_layouts)
        resource_capabilities.register(
            ProjectResourceKind.VECTOR,
            capabilities,
        )
        scene_mutations.register_owner(
            VectorSceneMutationOwner(
                assets,
                compositions.layers,
                current_composition_id,
            )
        )
        edits = document.edits
        selection = VectorObjectSelectionController(selection_changed)
        targets = VectorAuthoringTargetResolver(
            assets=assets,
            layers=compositions.layers,
            current_composition_id=current_composition_id,
            current_scene=current_scene,
            coordinates=coordinates,
        )
        nodes = VectorNodeEditController(
            assets=assets,
            edits=edits,
            projection=projection,
            targets=targets,
            layer_selection=layer_selection,
            object_selection=selection,
            changed=lambda: changed(None),
            selection_changed=node_selection_changed,
        )
        texts = VectorTextEditController(
            assets=assets,
            edits=edits,
            projection=projection,
            targets=targets,
            layer_selection=layer_selection,
            object_selection=selection,
            layouts=text_layouts,
            changed=lambda: changed(None),
            state_changed=text_edit_changed,
            options_changed=options_changed,
        )
        interaction = VectorInteractionController(
            assets=assets,
            edits=edits,
            layer_selection=layer_selection,
            object_selection=selection,
            current_scene=current_scene,
            options_changed=options_changed,
            targets=targets,
        )
        conversions = VectorConversionService(
            assets=assets,
            raster_assets=raster_assets,
            layers=compositions.layers,
            layer_edits=compositions.layer_edits,
            vector_edits=edits,
            lifetime=compositions.resource_lifetime,
            pixel_selection=pixel_selection,
            object_selection=selection,
            execution_scope=execution_scope,
            latest_requests=latest_requests,
            changed=lambda: changed(None),
            completed=conversion_completed,
        )
        mask_paths = VectorMaskPathCache(text_layouts=text_layouts)
        if cache_registry is not None:
            cache_registry.attach_geometry_cache(
                mask_paths,
                consumer_id="vector_mask_paths",
            )
        layer_effects.register(
            VectorMaskEffect,
            VectorMaskRenderOwner(projection, mask_paths),
        )
        masks = document.masks
        return VectorDomainComponents(
            assets=assets,
            layers=layers,
            edits=edits,
            selection=selection,
            interaction=interaction,
            conversions=conversions,
            masks=masks,
            targets=targets,
            projection=projection,
            nodes=nodes,
            texts=texts,
            text_layouts=text_layouts,
        )
