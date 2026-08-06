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

"""Construct and register CuteCanvas's always-on editor collaborators."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QRect, QRectF
from qpane.sdk.cache import CacheRegistry, cache_detail_provider
from qpane.sdk.diagnostics import Diagnostics
from qpane.sdk.execution import ExecutionScope
from qpane.sdk.rendering import PyramidManager, SceneRegionRasterizer, View
from qpane.sdk.scene import (
    LayerEffectRenderRegistry,
    LayerSourceCapabilities,
    SceneProviderRegistry,
)

from ..composition import CompositionService
from ..composition.scene_adapter import CompositionSceneAdapter
from ..core import CuteCanvasState
from ..core.config import Config
from ..coverage import CoverageShapeConfiguration
from ..document import CanvasDocument
from ..fill import PaintBucketCoordinator, SelectionFillCoordinator
from ..masks.canvas_aperture import ActiveMaskCanvasAperture
from ..masks.coordinates import ActiveMaskLayerCoordinates
from ..painting import (
    BrushDynamics,
    BrushPreset,
    PaintingCoordinator,
    PaintTargetIdentity,
)
from ..painting.clone_model import CloneStampState
from ..painting.clone_operation import CloneStampOperation
from ..placed.mutations import PlacedAssetSceneMutationOwner
from ..placed.rasterization import PlacedAssetRasterizationService
from ..placed.store import PlacedAssetStore
from ..placed.workflow import PlacedAssetCompletion, PlacedAssetWorkflow
from ..raster.assets import EditableRasterAssetStore
from ..raster.clone_target import EditableRasterCloneTarget
from ..raster.floating_layers import EditableRasterFloatingLayerOwner
from ..raster.layers import (
    EditableRasterLayerController,
    EditableRasterSceneMutationOwner,
)
from ..raster.paint_target import EditableRasterPaintTargetOwner
from ..raster.pixel_edits import EditableRasterPixelMutationOwner
from ..raster.structure_mutations import EditableRasterStructureMutationOwner
from ..rendering.transient_rasters import TransientRasterRenderCoordinator
from ..resources import (
    LayerRasterizationCompletion,
    LayerResourceRasterizationRouter,
    ProjectResourceKind,
    ProjectResourceReference,
    ProjectResourceStore,
)
from ..resources.active_raster import ActiveRasterResolver
from ..resources.active_raster_coordinates import ActiveRasterCoordinateResolver
from ..resources.composition_rasterization import (
    CompositionResourceRasterizationService,
)
from ..resources.descriptor_factory import ProjectResourceLayerDescriptorFactory
from ..resources.image_documents import ImageDocumentWorkflow
from ..resources.install import (
    ProjectResourceCallbacks,
    ProjectResourceDomainInstaller,
)
from ..resources.layer_operations import LayerResourceOperations, ResourceForkOwner
from ..resources.lifecycle import ProjectResourceLifecycleOwner
from ..resources.source_capabilities import ProjectResourceSourceCapabilities
from ..runtime.latest_requests import DocumentLatestRequestRegistry
from ..scene.layer_assembly import CompositionLayerSceneAssembler
from ..scene.layer_edge_preview import LayerEdgePreviewStore
from ..scene.layer_geometry import LayerGeometryPolicy, LayerGeometryResolver
from ..scene.layer_move import SceneLayerMoveController
from ..scene.layer_selection import SceneLayerSelectionController
from ..scene.movement_interaction import SceneLayerMovementInteraction
from ..scene.movement_mutations import LayerMovementMutationOwner
from ..scene.mutations import SceneMutationCoordinator
from ..scene.pixel_edits import LayerPixelContentChange, LayerPixelMutationCoordinator
from ..scene.pixel_owners import LayerPixelOwnerRegistry
from ..scene.raster_mutations import (
    RasterBoundsCompletion,
    RasterLayerMutationCoordinator,
)
from ..scene.source_capabilities import EditorSourceCapabilities
from ..scene.transform_preview import SceneLayerTransformPreview
from ..scene.transform_session import SceneLayerTransformController
from ..scene.viewport_selection import ViewportSceneSelection
from ..selection import (
    PixelSelectionModificationCoordinator,
    PixelSelectionPaintTargetOwner,
    PixelSelectionService,
    PixelSelectionState,
)
from ..snapping.system import SnappingSubsystem
from ..tools import Tools
from ..types import LayerEdgeModificationResult, PixelSelectionModificationResult
from ..ui import CursorBuilder
from ..vector.conversion import VectorConversionCompletion
from ..vector.install import VectorDomainComponents, VectorDomainInstaller
from ..vector.tools import install_vector_tools
from .floating_layers import FloatingLayerPromotionRegistry
from .interaction import EditorInteractionCoordinator
from .layer_edge_modification import LayerEdgeModificationCoordinator
from .layer_edge_targets import LayerEdgeEditRegistry
from .move_configuration import MoveToolConfiguration
from .movement import EditorMovementInteraction
from .operation_resolution import EditorOperationResolver
from .paint_destination import InteractivePaintDestinationCoordinator
from .pixel_movement import SelectedPixelMovementController
from .policy import EditorPolicyController
from .selection_projection import LayerSelectionProjectionCache
from .source_operations import (
    EditorSourceOperationRegistry,
    EditorSourceOperations,
)
from .transform_coordinator import EditorTransformCoordinator
from .transform_interaction import SceneLayerTransformInteraction

if TYPE_CHECKING:
    from ..canvas import CuteCanvas
    from ..masks.live_preview_store import MaskLivePreviewStore


@dataclass(frozen=True, slots=True)
class EditorRootCallbacks:
    """Facade callbacks needed by always-on editor collaborators."""

    composition_history_changed: Callable[[uuid.UUID], None]
    composition_layers_changed: Callable[[uuid.UUID], None]
    pixel_selection_changed: Callable[[PixelSelectionState], None]
    pixel_selection_modification_completed: Callable[
        [PixelSelectionModificationResult], None
    ]
    layer_edge_modification_completed: Callable[[LayerEdgeModificationResult], None]
    transform_changed: Callable[[], None]
    transform_preview_changed: Callable[[], None]
    transform_state_changed: Callable[[], None]
    raster_structure_changed: Callable[[], None]
    raster_bounds_completed: Callable[[RasterBoundsCompletion], None]
    scene_content_changed: Callable[[QRect | QRectF | None], None]
    resource_content_changed: Callable[[uuid.UUID], None]
    layer_pixels_changed: Callable[[LayerPixelContentChange], None]
    pixel_move_preview_changed: Callable[[], None]
    active_mask_id: Callable[[], uuid.UUID | None]
    placed_asset_completed: Callable[[PlacedAssetCompletion], None]
    layer_rasterization_completed: Callable[[LayerRasterizationCompletion], None]
    current_composition_id: Callable[[], uuid.UUID | None]
    current_edit_scope_id: Callable[[], uuid.UUID | None]
    paint_target_changed: Callable[[PaintTargetIdentity | None], None]
    clone_stamp_changed: Callable[[CloneStampState], None]
    default_paint_target_available: Callable[[], bool]
    vector_selection_changed: Callable[[], None]
    vector_node_selection_changed: Callable[[], None]
    vector_text_edit_changed: Callable[[], None]
    vector_content_changed: Callable[[], None]
    vector_options_changed: Callable[[], None]
    vector_conversion_completed: Callable[[VectorConversionCompletion], None]


@dataclass(frozen=True, slots=True)
class EditorRootInputs:
    """Existing lifecycle owners and state supplied to the editor root."""

    qpane: CuteCanvas
    document: CanvasDocument
    state: CuteCanvasState
    settings: Config
    execution_scope: ExecutionScope
    document_execution_scope: ExecutionScope
    latest_requests: DocumentLatestRequestRegistry
    mask_live_previews: MaskLivePreviewStore
    cache_registry: CacheRegistry | None
    diagnostics: Diagnostics
    layer_selection: SceneLayerSelectionController
    transform_preview: SceneLayerTransformPreview
    selection_projections: LayerSelectionProjectionCache
    floating_promotions: FloatingLayerPromotionRegistry
    editor_policy: EditorPolicyController
    move_configuration: MoveToolConfiguration
    callbacks: EditorRootCallbacks


@dataclass(frozen=True, slots=True)
class EditorRootComponents:
    """Always-on editor collaborators installed into the CuteCanvas facade."""

    scene_providers: SceneProviderRegistry
    render_source_capabilities: LayerSourceCapabilities
    editor_source_capabilities: EditorSourceCapabilities
    project_resources: ProjectResourceStore
    project_resource_descriptors: ProjectResourceLayerDescriptorFactory
    project_resource_capabilities: ProjectResourceSourceCapabilities
    project_resource_lifecycle: ProjectResourceLifecycleOwner
    compositions: CompositionService
    editable_raster_assets: EditableRasterAssetStore
    editable_raster_layers: EditableRasterLayerController
    placed_assets: PlacedAssetStore
    image_documents: ImageDocumentWorkflow
    active_raster: ActiveRasterResolver
    active_raster_coordinates: ActiveRasterCoordinateResolver
    layer_resource_operations: LayerResourceOperations
    placed_asset_workflow: PlacedAssetWorkflow
    placed_asset_rasterization: PlacedAssetRasterizationService
    composition_rasterization: CompositionResourceRasterizationService
    resource_rasterization: LayerResourceRasterizationRouter
    painting: PaintingCoordinator
    clone_stamp: CloneStampOperation
    paint_bucket: PaintBucketCoordinator
    selection_fill: SelectionFillCoordinator
    snapping: SnappingSubsystem
    coverage_shape_configuration: CoverageShapeConfiguration
    raster_paint_target: EditableRasterPaintTargetOwner
    vector: VectorDomainComponents
    pixel_selection: PixelSelectionService
    pixel_selection_modifications: PixelSelectionModificationCoordinator
    layer_edge_targets: LayerEdgeEditRegistry
    layer_edge_modifications: LayerEdgeModificationCoordinator
    layer_geometry: LayerGeometryResolver
    layer_assembler: CompositionLayerSceneAssembler
    scene_rasterizer: SceneRegionRasterizer
    view: View
    scene_mutations: SceneMutationCoordinator
    scene_movement: SceneLayerMoveController
    scene_transform: SceneLayerTransformController
    scene_movement_interaction: SceneLayerMovementInteraction
    scene_transform_interaction: EditorTransformCoordinator
    raster_mutations: RasterLayerMutationCoordinator
    pixel_owners: LayerPixelOwnerRegistry
    pixel_mutations: LayerPixelMutationCoordinator
    editor_interaction: EditorInteractionCoordinator
    raster_floating_owner: EditableRasterFloatingLayerOwner
    selected_pixel_movement: SelectedPixelMovementController
    editor_movement_interaction: EditorMovementInteraction
    operation_resolver: EditorOperationResolver
    paint_destination: InteractivePaintDestinationCoordinator
    active_mask_coordinates: ActiveMaskLayerCoordinates
    active_mask_aperture: ActiveMaskCanvasAperture
    composition_scene_adapter: CompositionSceneAdapter
    tools: Tools
    cursor_builder: CursorBuilder


class EditorCompositionRoot:
    """Own construction order and cross-domain registration for core editing."""

    def build(self, inputs: EditorRootInputs) -> EditorRootComponents:
        """Construct one complete always-on editor collaboration graph."""
        callbacks = inputs.callbacks
        scene_providers = SceneProviderRegistry()
        scene_providers.register_post_processor(inputs.transform_preview)
        render_source_capabilities = LayerSourceCapabilities.create()
        editor_source_capabilities = EditorSourceCapabilities.create()
        layer_effects = LayerEffectRenderRegistry()
        pyramid_manager = PyramidManager(
            config=inputs.settings,
            execution_scope=inputs.execution_scope,
            parent=inputs.qpane,
        )
        resource_domain = ProjectResourceDomainInstaller().install(
            execution_scope=inputs.document_execution_scope,
            latest_requests=inputs.latest_requests,
            document=inputs.document.resources,
            render_capabilities=render_source_capabilities,
            editor_capabilities=editor_source_capabilities,
            layer_effects=layer_effects,
            callbacks=ProjectResourceCallbacks(
                resource_content_changed=callbacks.resource_content_changed,
                placed_asset_completed=callbacks.placed_asset_completed,
                layer_rasterization_completed=(callbacks.layer_rasterization_completed),
                current_edit_scope_id=callbacks.current_edit_scope_id,
                current_composition_id=callbacks.current_composition_id,
            ),
        )
        project_resources = resource_domain.resources
        compositions = resource_domain.compositions
        project_resource_lifecycle = resource_domain.lifecycle
        editable_raster_assets = resource_domain.editable_raster_assets
        editable_raster_presentation = resource_domain.editable_raster_presentation
        editable_raster_layers = resource_domain.editable_raster_layers
        placed_assets = resource_domain.placed_assets
        image_documents = resource_domain.image_documents
        active_raster = resource_domain.active_raster
        layer_resource_operations = resource_domain.layer_operations
        placed_asset_workflow = resource_domain.placed_asset_workflow
        placed_asset_rasterization = resource_domain.placed_asset_rasterization
        composition_rasterization = resource_domain.composition_rasterization
        resource_rasterization = resource_domain.rasterization
        pixel_selection = resource_domain.pixel_selection
        layer_assembler = resource_domain.layer_assembler
        project_resource_descriptors = resource_domain.descriptors
        project_resource_capabilities = resource_domain.capabilities

        view = View(
            qpane=inputs.qpane,
            state=inputs.state,
            pyramid_manager=pyramid_manager,
            execution_scope=inputs.execution_scope,
            scene_providers=scene_providers,
            source_capabilities=render_source_capabilities,
            layer_effects=layer_effects,
        )
        scene_mutations = SceneMutationCoordinator(
            scene_provider=view.current_scene_descriptor,
            edit_controller=compositions.edit_controller,
        )
        vector = VectorDomainInstaller().install(
            compositions=compositions,
            document=inputs.document.vectors,
            resources=project_resources,
            resource_descriptors=project_resource_descriptors,
            resource_capabilities=project_resource_capabilities,
            resource_lifecycle=project_resource_lifecycle,
            layer_assembler=layer_assembler,
            source_capabilities=render_source_capabilities,
            editor_source_capabilities=editor_source_capabilities,
            scene_mutations=scene_mutations,
            current_composition_id=callbacks.current_composition_id,
            current_history_scope_id=callbacks.current_edit_scope_id,
            changed=lambda _bounds: callbacks.vector_content_changed(),
            selection_changed=callbacks.vector_selection_changed,
            node_selection_changed=callbacks.vector_node_selection_changed,
            text_edit_changed=callbacks.vector_text_edit_changed,
            options_changed=callbacks.vector_options_changed,
            layer_selection=inputs.layer_selection,
            current_scene=view.current_scene_descriptor,
            coordinates=view.coordinates,
            raster_assets=editable_raster_assets,
            pixel_selection=pixel_selection,
            execution_scope=inputs.document_execution_scope,
            latest_requests=inputs.latest_requests,
            conversion_completed=callbacks.vector_conversion_completed,
            layer_effects=layer_effects,
            cache_registry=inputs.cache_registry,
        )
        layer_resource_operations.register_fork_owner(
            ProjectResourceKind.VECTOR,
            ResourceForkOwner(
                fork=vector.assets.fork,
                remove=vector.assets.remove,
            ),
        )
        resource_rasterization.register(
            ProjectResourceKind.VECTOR,
            lambda composition_id, history_scope_id, public_scene_id, layer_id, pixel_size: (
                vector.conversions.request_rasterization(
                    composition_id=composition_id,
                    history_scope_id=history_scope_id,
                    public_scene_id=public_scene_id,
                    layer_id=layer_id,
                    pixel_size=pixel_size,
                )
            ),
        )
        view.presenter.set_vector_text_layouts(vector.text_layouts)
        pixel_owners = LayerPixelOwnerRegistry()
        layer_geometry = LayerGeometryResolver(
            editor_source_capabilities,
            lambda layer: (
                instance.geometry
                if (
                    instance := compositions.layers.layer(
                        layer.scene_id,
                        layer.layer_id,
                    )
                )
                is not None
                else LayerGeometryPolicy()
            ),
        )
        scene_transform = SceneLayerTransformController(
            inputs.layer_selection,
            inputs.transform_preview,
            scene_mutations,
            layer_geometry,
        )
        movement_mutations = LayerMovementMutationOwner(
            scene_provider=view.current_scene_descriptor,
            composition_id=callbacks.current_composition_id,
            layers=compositions.layers,
            edits=compositions.edit_controller,
        )
        scene_movement = SceneLayerMoveController(
            selection=inputs.layer_selection,
            preview=inputs.transform_preview,
            mutations=movement_mutations,
            geometry=layer_geometry,
            scene_provider=view.current_scene_descriptor,
        )
        scene_movement_interaction = SceneLayerMovementInteraction(
            movement=scene_movement,
            selection=inputs.layer_selection,
            geometry=layer_geometry,
            scene_provider=view.current_scene_descriptor,
            hit_test=view.scene_selection_hit_test,
            panel_to_scene=view.panel_to_scene_point,
            publish_change=callbacks.transform_changed,
            refresh_preview=callbacks.transform_preview_changed,
        )
        layer_transform_interaction = SceneLayerTransformInteraction(
            transforms=scene_transform,
            panel_to_scene=view.panel_to_scene_point,
            scene_to_panel=view.scene_to_panel_point,
            publish_change=callbacks.transform_changed,
            refresh_preview=callbacks.transform_preview_changed,
        )
        painting = PaintingCoordinator(
            scenes=scene_mutations,
            coordinates=view.coordinates,
            preset=BrushPreset(
                size=float(inputs.settings.default_brush_size),
                dynamics=BrushDynamics(
                    pressure_size=(
                        1.0 if inputs.settings.pen_pressure_enabled else 0.0
                    ),
                    minimum_pressure_ratio=inputs.settings.pen_pressure_min_ratio,
                    pressure_gamma=inputs.settings.pen_pressure_gamma,
                ),
            ),
            changed=callbacks.paint_target_changed,
            resource_lifetime=compositions.resource_lifetime,
        )
        if inputs.cache_registry is not None:
            inputs.cache_registry.attach_brush_tip_cache(painting.compositor.tips)
        raster_paint_history = inputs.document.resources.raster_paint_history
        raster_paint_target = EditableRasterPaintTargetOwner(
            assets=editable_raster_assets,
            selections=pixel_selection,
            history=raster_paint_history,
            changed=callbacks.scene_content_changed,
            structure_changed=callbacks.raster_structure_changed,
            presentation_state=editable_raster_presentation,
            compositor=painting.compositor,
        )
        painting.registry.register(raster_paint_target)
        painting.registry.register(
            PixelSelectionPaintTargetOwner(pixel_selection, painting.compositor)
        )
        raster_clone_target = EditableRasterCloneTarget(
            assets=editable_raster_assets,
            selections=pixel_selection,
            history=raster_paint_history,
            changed=callbacks.scene_content_changed,
            structure_changed=callbacks.raster_structure_changed,
            presentation_state=editable_raster_presentation,
            compositor=painting.compositor,
            scene_rasterizer=resource_domain.scene_rasterizer,
        )
        clone_stamp = CloneStampOperation(
            target=raster_clone_target,
            current_scene=view.current_scene_descriptor,
            selected_layer=lambda: inputs.layer_selection.resolve(
                view.current_scene_descriptor()
            ),
            coordinates=view.coordinates,
            changed=callbacks.clone_stamp_changed,
        )
        paint_bucket = PaintBucketCoordinator(
            painting=painting,
            selections=pixel_selection,
            execution_scope=inputs.execution_scope,
        )
        selection_fill = SelectionFillCoordinator(
            painting=painting,
            selections=pixel_selection,
        )
        raster_mutations = RasterLayerMutationCoordinator(view.current_scene_descriptor)
        pixel_mutations = LayerPixelMutationCoordinator(
            scene_mutations=scene_mutations,
            layer_selection=inputs.layer_selection,
            pixel_selection=pixel_selection,
            owners=pixel_owners,
            edit_controller=compositions.edit_controller,
            changed=callbacks.layer_pixels_changed,
        )
        editor_interaction = EditorInteractionCoordinator(
            active_scene=view.current_scene_descriptor,
            scene_mutations=scene_mutations,
            layer_selection=inputs.layer_selection,
            pixel_selection=pixel_selection,
            pixel_mutations=pixel_mutations,
            source_coverage=editor_source_capabilities.coverage,
            selection_projections=inputs.selection_projections,
        )
        pixel_selection_modifications = PixelSelectionModificationCoordinator(
            active_scene=view.current_scene_descriptor,
            selections=pixel_selection,
            execution_scope=inputs.execution_scope,
            latest_requests=inputs.latest_requests,
            completed=callbacks.pixel_selection_modification_completed,
        )
        layer_edge_targets = LayerEdgeEditRegistry()
        layer_edge_previews = LayerEdgePreviewStore()
        layer_edge_modifications = LayerEdgeModificationCoordinator(
            active_scene=view.current_scene_descriptor,
            targets=layer_edge_targets,
            previews=layer_edge_previews,
            execution_scope=inputs.execution_scope,
            latest_requests=inputs.latest_requests,
            preview_changed=callbacks.pixel_move_preview_changed,
            completed=callbacks.layer_edge_modification_completed,
        )

        raster_floating_owner = EditableRasterFloatingLayerOwner(
            assets=editable_raster_assets,
            layers=compositions.layers,
            current_composition_id=callbacks.current_composition_id,
            changed=callbacks.raster_structure_changed,
        )
        inputs.floating_promotions.register(raster_floating_owner)
        selected_pixel_movement = SelectedPixelMovementController(
            active_scene=view.current_scene_descriptor,
            scene_mutations=scene_mutations,
            layer_selection=inputs.layer_selection,
            pixel_selection=pixel_selection,
            pixel_owners=pixel_owners,
            history=inputs.document.floating_history,
            session_id=inputs.qpane.viewSession().session_id,
            selection_projections=inputs.selection_projections,
            preview_changed=callbacks.pixel_move_preview_changed,
            promotions=inputs.floating_promotions,
        )
        source_operations = EditorSourceOperationRegistry()
        source_operations.register_resolver(
            ProjectResourceReference,
            lambda source: _project_resource_operations(
                project_resources,
                source,
            ),
        )
        operation_resolver = EditorOperationResolver(
            active_scene=view.current_scene_descriptor,
            scene_mutations=scene_mutations,
            layer_selection=inputs.layer_selection,
            pixel_selection=pixel_selection,
            selected_pixels=selected_pixel_movement.target_resolver,
            floating_pixels_active=lambda: selected_pixel_movement.active,
            floating_pixels_can_begin=selected_pixel_movement.can_begin,
            active_paint_target=lambda: painting.identity,
            default_paint_target_available=callbacks.default_paint_target_available,
            paint_target_supported=painting.supports_context,
            pixel_owners=pixel_owners,
            layer_geometry=layer_geometry,
            source_operations=source_operations,
            capability_allowed=inputs.editor_policy.allows,
        )
        paint_destination = InteractivePaintDestinationCoordinator(
            active_scene=view.current_scene_descriptor,
            selection=inputs.layer_selection,
            painting=painting,
            operations=operation_resolver,
            rasters=editable_raster_layers,
            policy=lambda: inputs.editor_policy.policy,
            capability_allowed=inputs.editor_policy.allows,
            scene_changed=callbacks.raster_structure_changed,
        )
        scene_transform_interaction = EditorTransformCoordinator(
            pixels=selected_pixel_movement,
            layers=layer_transform_interaction,
            operations=operation_resolver,
            changed=callbacks.transform_state_changed,
        )
        snapping = SnappingSubsystem.create(
            active_scene=view.current_scene_descriptor,
            geometry=layer_geometry,
            pixel_selection=pixel_selection,
            panel_to_scene=view.panel_to_scene_point,
            scene_to_panel=view.scene_to_panel_point,
            viewport_zoom=lambda: view.viewport.zoom,
            changed=callbacks.pixel_move_preview_changed,
        )
        coverage_shape_configuration = CoverageShapeConfiguration(
            callbacks.pixel_move_preview_changed
        )
        editor_movement_interaction = EditorMovementInteraction(
            pixels=selected_pixel_movement,
            layers=scene_movement_interaction,
            operations=operation_resolver,
            panel_to_scene=view.panel_to_scene_point,
            refresh_preview=callbacks.pixel_move_preview_changed,
            snapping=snapping.movement,
            configuration=inputs.move_configuration,
        )
        transient_rasters = TransientRasterRenderCoordinator(
            editor_source_capabilities,
            inputs.mask_live_previews,
            layer_edge_previews,
            view.current_scene_descriptor,
        )
        view.presenter.set_transient_raster_provider(
            lambda render_items: transient_rasters.compile(
                selected_pixel_movement.raster_preview,
                render_items,
            )
        )
        view.presenter.set_transient_raster_target_provider(
            lambda: transient_rasters.target(selected_pixel_movement.raster_preview)
        )
        active_mask_coordinates = ActiveMaskLayerCoordinates(
            active_mask_id=callbacks.active_mask_id,
            active_scene=view.coordinate_scene_descriptor,
            coordinates=view.coordinates,
        )
        active_raster_coordinates = ActiveRasterCoordinateResolver(
            rasters=active_raster,
            coordinates=view.coordinates,
            preferred_layer_id=lambda: (
                None
                if inputs.layer_selection.current is None
                else inputs.layer_selection.current.layer_id
            ),
        )
        active_mask_aperture = ActiveMaskCanvasAperture(
            active_mask_id=callbacks.active_mask_id,
            active_scene=view.coordinate_scene_descriptor,
            pixel_selection=pixel_selection,
        )

        scene_mutations.register_owner(
            EditableRasterSceneMutationOwner(
                editable_raster_assets,
                compositions.layers,
                callbacks.current_composition_id,
            )
        )
        scene_mutations.register_owner(
            PlacedAssetSceneMutationOwner(
                compositions.layers,
                compositions.layer_edits,
                placed_assets,
                callbacks.current_composition_id,
            )
        )
        raster_mutations.register_owner(
            EditableRasterStructureMutationOwner(
                editable_raster_assets,
                edits=compositions.edit_controller,
                execution_scope=inputs.document_execution_scope,
                latest_requests=inputs.latest_requests,
                changed=callbacks.raster_structure_changed,
                completed=callbacks.raster_bounds_completed,
            )
        )
        pixel_owners.register(
            EditableRasterPixelMutationOwner(
                editable_raster_assets,
                changed=callbacks.scene_content_changed,
                structure_changed=callbacks.raster_structure_changed,
            )
        )

        composition_scene_adapter = CompositionSceneAdapter(
            compositions=compositions,
            assembler=layer_assembler,
            current_composition_id=callbacks.current_composition_id,
            viewport_selection=ViewportSceneSelection(
                inputs.document,
                compositions,
                layer_assembler,
            ),
            current_viewport_spec=lambda: inputs.qpane.viewSession().viewport_spec,
        )
        scene_providers.register_replacement(composition_scene_adapter)
        tools = Tools(parent=inputs.qpane)
        install_vector_tools(tools.registerTool)
        cursor_builder = CursorBuilder()
        view.register_diagnostics(inputs.diagnostics)
        inputs.diagnostics.register_cache_providers(
            cache_detail_provider,
            tier="detail",
        )
        return EditorRootComponents(
            scene_providers=scene_providers,
            render_source_capabilities=render_source_capabilities,
            editor_source_capabilities=editor_source_capabilities,
            project_resources=project_resources,
            project_resource_descriptors=project_resource_descriptors,
            project_resource_capabilities=project_resource_capabilities,
            project_resource_lifecycle=project_resource_lifecycle,
            compositions=compositions,
            editable_raster_assets=editable_raster_assets,
            editable_raster_layers=editable_raster_layers,
            placed_assets=placed_assets,
            image_documents=image_documents,
            active_raster=active_raster,
            active_raster_coordinates=active_raster_coordinates,
            layer_resource_operations=layer_resource_operations,
            placed_asset_workflow=placed_asset_workflow,
            placed_asset_rasterization=placed_asset_rasterization,
            composition_rasterization=composition_rasterization,
            resource_rasterization=resource_rasterization,
            painting=painting,
            clone_stamp=clone_stamp,
            paint_bucket=paint_bucket,
            selection_fill=selection_fill,
            snapping=snapping,
            coverage_shape_configuration=coverage_shape_configuration,
            raster_paint_target=raster_paint_target,
            vector=vector,
            pixel_selection=pixel_selection,
            pixel_selection_modifications=pixel_selection_modifications,
            layer_edge_targets=layer_edge_targets,
            layer_edge_modifications=layer_edge_modifications,
            layer_geometry=layer_geometry,
            layer_assembler=layer_assembler,
            scene_rasterizer=resource_domain.scene_rasterizer,
            view=view,
            scene_mutations=scene_mutations,
            scene_movement=scene_movement,
            scene_transform=scene_transform,
            scene_movement_interaction=scene_movement_interaction,
            scene_transform_interaction=scene_transform_interaction,
            raster_mutations=raster_mutations,
            pixel_owners=pixel_owners,
            pixel_mutations=pixel_mutations,
            editor_interaction=editor_interaction,
            raster_floating_owner=raster_floating_owner,
            selected_pixel_movement=selected_pixel_movement,
            editor_movement_interaction=editor_movement_interaction,
            operation_resolver=operation_resolver,
            paint_destination=paint_destination,
            active_mask_coordinates=active_mask_coordinates,
            active_mask_aperture=active_mask_aperture,
            composition_scene_adapter=composition_scene_adapter,
            tools=tools,
            cursor_builder=cursor_builder,
        )


def _project_resource_operations(
    resources: ProjectResourceStore,
    source: object,
) -> EditorSourceOperations:
    """Return editor alternatives from one resource's authoritative kind."""
    if not isinstance(source, ProjectResourceReference):
        return EditorSourceOperations()
    record = resources.resolve(source)
    if record is None:
        return EditorSourceOperations()
    return EditorSourceOperations(
        rasterize=record.kind
        in {
            ProjectResourceKind.IMPORTED_RASTER,
            ProjectResourceKind.LINKED_RASTER,
            ProjectResourceKind.VECTOR,
            ProjectResourceKind.COMPOSITION,
        },
        edit_contents=record.kind is ProjectResourceKind.COMPOSITION,
    )
