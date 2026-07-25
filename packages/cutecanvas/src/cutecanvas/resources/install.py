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

"""Install the authoritative project-resource graph and its payload owners."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from qpane.sdk.execution import ExecutionScope
from qpane.sdk.rendering import SceneRegionRasterizer
from qpane.sdk.scene import LayerEffectRenderRegistry, LayerSourceCapabilities

from ..composition import CompositionService
from ..placed.descriptor_factory import PlacedAssetLayerDescriptorFactory
from ..placed.rasterization import PlacedAssetRasterizationService
from ..placed.source_capabilities import PlacedAssetSourceCapabilities
from ..placed.store import PlacedAssetStore
from ..placed.workflow import PlacedAssetCompletion, PlacedAssetWorkflow
from ..raster.assets import EditableRasterAssetStore
from ..raster.descriptor_factory import EditableRasterLayerDescriptorFactory
from ..raster.layers import EditableRasterLayerController
from ..raster.presentation_state import EditableRasterPresentationState
from ..raster.source_resolver import EditableRasterSourceCapabilities
from ..runtime.latest_requests import DocumentLatestRequestRegistry
from ..scene.layer_assembly import CompositionLayerSceneAssembler
from ..scene.source_capabilities import EditorSourceCapabilities
from ..selection import PixelSelectionService
from .active_raster import ActiveRasterResolver
from .composition_rasterization import CompositionResourceRasterizationService
from .composition_rendering import CompositionResourceRenderingOwner
from .descriptor_factory import ProjectResourceLayerDescriptorFactory
from .document_core import DocumentResourceCore
from .image_documents import ImageDocumentWorkflow
from .layer_operations import LayerResourceOperations
from .lifecycle import ProjectResourceLifecycleOwner
from .model import ProjectResourceKind, ProjectResourceReference
from .rasterization import (
    LayerRasterizationCompletion,
    LayerResourceRasterizationRouter,
)
from .source_capabilities import ProjectResourceSourceCapabilities
from .store import ProjectResourceStore


@dataclass(frozen=True, slots=True)
class ProjectResourceCallbacks:
    """Provide resource-domain observations without coupling to the widget."""

    resource_content_changed: Callable[[uuid.UUID], None]
    placed_asset_completed: Callable[[PlacedAssetCompletion], None]
    layer_rasterization_completed: Callable[[LayerRasterizationCompletion], None]
    current_edit_scope_id: Callable[[], uuid.UUID | None]
    current_composition_id: Callable[[], uuid.UUID | None]


@dataclass(frozen=True, slots=True)
class ProjectResourceComponents:
    """Return the complete resource graph and its focused domain collaborators."""

    resources: ProjectResourceStore
    descriptors: ProjectResourceLayerDescriptorFactory
    capabilities: ProjectResourceSourceCapabilities
    lifecycle: ProjectResourceLifecycleOwner
    compositions: CompositionService
    editable_raster_assets: EditableRasterAssetStore
    editable_raster_presentation: EditableRasterPresentationState
    editable_raster_layers: EditableRasterLayerController
    placed_assets: PlacedAssetStore
    image_documents: ImageDocumentWorkflow
    active_raster: ActiveRasterResolver
    layer_operations: LayerResourceOperations
    placed_asset_workflow: PlacedAssetWorkflow
    placed_asset_rasterization: PlacedAssetRasterizationService
    composition_rasterization: CompositionResourceRasterizationService
    rasterization: LayerResourceRasterizationRouter
    pixel_selection: PixelSelectionService
    layer_assembler: CompositionLayerSceneAssembler
    scene_rasterizer: SceneRegionRasterizer


class ProjectResourceDomainInstaller:
    """Build one resource graph and register every authoritative payload route."""

    def install(
        self,
        *,
        execution_scope: ExecutionScope,
        latest_requests: DocumentLatestRequestRegistry,
        document: DocumentResourceCore,
        render_capabilities: LayerSourceCapabilities,
        editor_capabilities: EditorSourceCapabilities,
        layer_effects: LayerEffectRenderRegistry,
        callbacks: ProjectResourceCallbacks,
    ) -> ProjectResourceComponents:
        """Install resource identity, lifecycle, rendering, and history routes."""
        resources = document.resources
        compositions = document.compositions
        lifecycle = document.lifecycle
        raster_assets = document.editable_raster_assets
        raster_presentation = EditableRasterPresentationState()
        raster_layers = EditableRasterLayerController(
            assets=raster_assets,
            layers=compositions.layers,
            layer_edits=compositions.layer_edits,
            current_composition_id=callbacks.current_composition_id,
        )

        placed_assets = document.placed_assets
        image_documents = document.image_documents
        active_raster = ActiveRasterResolver(
            compositions=compositions,
            resources=resources,
            imported=placed_assets,
            rasters=raster_assets,
            current_composition_id=callbacks.current_composition_id,
        )
        layer_operations = document.layer_operations
        placed_workflow, placed_rasterization = self._install_placed_workflows(
            execution_scope=execution_scope,
            latest_requests=latest_requests,
            compositions=compositions,
            raster_assets=raster_assets,
            placed_assets=placed_assets,
            callbacks=callbacks,
        )
        rasterization = LayerResourceRasterizationRouter(
            resources=resources,
            layers=compositions.layers,
        )
        for kind in (
            ProjectResourceKind.IMPORTED_RASTER,
            ProjectResourceKind.LINKED_RASTER,
        ):
            rasterization.register(kind, placed_rasterization.request)

        pixel_selection = document.pixel_selection

        layer_assembler = CompositionLayerSceneAssembler(
            layer_instances=compositions.layers.layers_for_composition,
            layer_revision=lambda: compositions.layers.revision,
        )
        descriptors, capabilities, scene_rasterizer = self._install_render_routes(
            resources=resources,
            compositions=compositions,
            raster_assets=raster_assets,
            raster_presentation=raster_presentation,
            placed_assets=placed_assets,
            layer_assembler=layer_assembler,
            render_capabilities=render_capabilities,
            editor_capabilities=editor_capabilities,
            layer_effects=layer_effects,
        )
        composition_rasterization = CompositionResourceRasterizationService(
            resources=resources,
            capabilities=capabilities,
            raster_assets=raster_assets,
            layers=compositions.layers,
            layer_edits=compositions.layer_edits,
            execution_scope=execution_scope,
            latest_requests=latest_requests,
            changed=callbacks.resource_content_changed,
            completed=callbacks.layer_rasterization_completed,
        )
        rasterization.register(
            ProjectResourceKind.COMPOSITION,
            composition_rasterization.request,
        )
        return ProjectResourceComponents(
            resources=resources,
            descriptors=descriptors,
            capabilities=capabilities,
            lifecycle=lifecycle,
            compositions=compositions,
            editable_raster_assets=raster_assets,
            editable_raster_presentation=raster_presentation,
            editable_raster_layers=raster_layers,
            placed_assets=placed_assets,
            image_documents=image_documents,
            active_raster=active_raster,
            layer_operations=layer_operations,
            placed_asset_workflow=placed_workflow,
            placed_asset_rasterization=placed_rasterization,
            composition_rasterization=composition_rasterization,
            rasterization=rasterization,
            pixel_selection=pixel_selection,
            layer_assembler=layer_assembler,
            scene_rasterizer=scene_rasterizer,
        )

    @staticmethod
    def _install_placed_workflows(
        *,
        execution_scope: ExecutionScope,
        latest_requests: DocumentLatestRequestRegistry,
        compositions: CompositionService,
        raster_assets: EditableRasterAssetStore,
        placed_assets: PlacedAssetStore,
        callbacks: ProjectResourceCallbacks,
    ) -> tuple[PlacedAssetWorkflow, PlacedAssetRasterizationService]:
        """Install imported and linked raster provenance workflows."""
        workflow = PlacedAssetWorkflow(
            assets=placed_assets,
            layers=compositions.layers,
            layer_edits=compositions.layer_edits,
            edits=compositions.edit_controller,
            execution_scope=execution_scope,
            latest_requests=latest_requests,
            current_scope_id=callbacks.current_composition_id,
            current_history_scope_id=callbacks.current_edit_scope_id,
            changed=callbacks.resource_content_changed,
            completed=callbacks.placed_asset_completed,
        )
        rasterization = PlacedAssetRasterizationService(
            placed_assets=placed_assets,
            raster_assets=raster_assets,
            layers=compositions.layers,
            layer_edits=compositions.layer_edits,
            execution_scope=execution_scope,
            latest_requests=latest_requests,
            changed=callbacks.resource_content_changed,
            completed=callbacks.placed_asset_completed,
            resource_completed=callbacks.layer_rasterization_completed,
        )
        return workflow, rasterization

    @staticmethod
    def _install_render_routes(
        *,
        resources: ProjectResourceStore,
        compositions: CompositionService,
        raster_assets: EditableRasterAssetStore,
        raster_presentation: EditableRasterPresentationState,
        placed_assets: PlacedAssetStore,
        layer_assembler: CompositionLayerSceneAssembler,
        render_capabilities: LayerSourceCapabilities,
        editor_capabilities: EditorSourceCapabilities,
        layer_effects: LayerEffectRenderRegistry,
    ) -> tuple[
        ProjectResourceLayerDescriptorFactory,
        ProjectResourceSourceCapabilities,
        SceneRegionRasterizer,
    ]:
        """Register one source-neutral reference across rendering capabilities."""
        descriptors = ProjectResourceLayerDescriptorFactory(resources)
        descriptors.register(
            ProjectResourceKind.RASTER,
            EditableRasterLayerDescriptorFactory(raster_assets),
        )
        placed_descriptors = PlacedAssetLayerDescriptorFactory(placed_assets)
        for kind in (
            ProjectResourceKind.IMPORTED_RASTER,
            ProjectResourceKind.LINKED_RASTER,
        ):
            descriptors.register(kind, placed_descriptors)
        layer_assembler.register_factory(descriptors)

        capabilities = ProjectResourceSourceCapabilities(resources)
        capabilities.register(
            ProjectResourceKind.RASTER,
            EditableRasterSourceCapabilities(
                raster_assets,
                raster_presentation,
            ),
        )
        placed_capabilities = PlacedAssetSourceCapabilities(placed_assets)
        for kind in (
            ProjectResourceKind.IMPORTED_RASTER,
            ProjectResourceKind.LINKED_RASTER,
        ):
            capabilities.register(kind, placed_capabilities)
        _register_resource_capabilities(
            render_capabilities,
            editor_capabilities,
            capabilities,
        )
        scene_rasterizer = SceneRegionRasterizer(
            render_capabilities,
            layer_effects=layer_effects,
        )
        composition_rendering = CompositionResourceRenderingOwner(
            resources=resources,
            compositions=compositions,
            assembler=layer_assembler,
            rasterizer=scene_rasterizer,
        )
        descriptors.register(
            ProjectResourceKind.COMPOSITION,
            composition_rendering,
        )
        capabilities.register(
            ProjectResourceKind.COMPOSITION,
            composition_rendering,
        )
        return descriptors, capabilities, scene_rasterizer


def _register_resource_capabilities(
    render_capabilities: LayerSourceCapabilities,
    editor_capabilities: EditorSourceCapabilities,
    resources: ProjectResourceSourceCapabilities,
) -> None:
    """Route one project reference through every supported capability family."""
    for registry in (
        render_capabilities.metadata,
        render_capabilities.rasters,
        render_capabilities.raster_patches,
        render_capabilities.hit_tests,
        render_capabilities.vectors,
        render_capabilities.hybrids,
        render_capabilities.sampled,
        editor_capabilities.coverage,
        editor_capabilities.pixel_presentation,
        editor_capabilities.content_bounds,
        editor_capabilities.storage_bounds,
        editor_capabilities.authored_bounds,
    ):
        registry.register(ProjectResourceReference, resources)
