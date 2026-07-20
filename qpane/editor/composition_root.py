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

"""Construct and register QPane's always-on editor collaborators."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QRect, QRectF, QSize

from ..cache import cache_detail_provider
from ..cache.registry import CacheRegistry
from ..catalog import Catalog, ImageCatalog
from ..catalog.descriptor_factory import CatalogLayerDescriptorFactory
from ..catalog.source_capabilities import CatalogSourceCapabilities
from ..catalog.source_reference import CatalogImageReference
from ..compare import CompareDividerInteraction, CompareService, ComparisonChange
from ..composition import CompositionService
from ..composition.mutations import (
    CatalogLayerMutationOwner,
)
from ..composition.scene_adapter import CompositionSceneAdapter
from ..concurrency import TaskExecutorProtocol
from ..core import Config, QPaneState
from ..core.diagnostics_broker import Diagnostics
from ..masks.coordinates import ActiveMaskLayerCoordinates
from ..painting import (
    BrushDynamics,
    BrushPreset,
    PaintingCoordinator,
    PaintTargetIdentity,
)
from ..placed.descriptor_factory import PlacedAssetLayerDescriptorFactory
from ..placed.history import PlacedAssetEdit, PlacedAssetEditOwner
from ..placed.mutations import PlacedAssetSceneMutationOwner
from ..placed.rasterization import PlacedAssetRasterizationService
from ..placed.resource_lifecycle import PlacedAssetResourceLifecycleOwner
from ..placed.source_capabilities import PlacedAssetSourceCapabilities
from ..placed.source_reference import PlacedAssetReference
from ..placed.store import PlacedAssetStore
from ..placed.workflow import PlacedAssetCompletion, PlacedAssetWorkflow
from ..raster.assets import EditableRasterAssetStore
from ..raster.descriptor_factory import EditableRasterLayerDescriptorFactory
from ..raster.floating_layers import EditableRasterFloatingLayerOwner
from ..raster.layers import (
    EditableRasterLayerController,
    EditableRasterSceneMutationOwner,
)
from ..raster.paint_target import EditableRasterPaintTargetOwner
from ..raster.pixel_edits import EditableRasterPixelMutationOwner
from ..raster.presentation_state import EditableRasterPresentationState
from ..raster.resource_lifecycle import EditableRasterResourceLifecycleOwner
from ..raster.source_reference import EditableRasterReference
from ..raster.source_resolver import EditableRasterSourceCapabilities
from ..raster.structure_mutations import EditableRasterStructureMutationOwner
from ..rendering import PyramidManager, View
from ..scene.effects import LayerEffectRenderRegistry
from ..scene.layer_assembly import CompositionLayerSceneAssembler
from ..scene.layer_selection import SceneLayerSelectionController
from ..scene.movement_interaction import SceneLayerMovementInteraction
from ..scene.mutations import SceneMutationCoordinator
from ..scene.pixel_edits import LayerPixelMutationCoordinator
from ..scene.pixel_owners import LayerPixelOwnerRegistry
from ..scene.raster_mutations import (
    RasterBoundsCompletion,
    RasterLayerMutationCoordinator,
)
from ..scene.registry import SceneProviderRegistry
from ..scene.source_capabilities import LayerSourceCapabilities
from ..scene.transform_preview import SceneLayerTransformPreview
from ..scene.transform_session import SceneLayerTransformController
from ..selection import (
    PixelSelectionEdit,
    PixelSelectionPaintTargetOwner,
    PixelSelectionService,
    PixelSelectionState,
)
from ..tools import Tools
from ..ui import CursorBuilder
from ..vector.conversion import VectorConversionCompletion
from ..vector.install import VectorDomainComponents, VectorDomainInstaller
from ..vector.source_reference import VectorDocumentReference
from ..vector.tools import install_vector_tools
from .floating_layers import FloatingLayerPromotionRegistry
from .interaction import EditorInteractionCoordinator
from .movement import EditorMovementInteraction
from .operation_resolution import (
    EditorOperationResolver,
    EditorSourceOperationRegistry,
    EditorSourceOperations,
)
from .pixel_movement import SelectedPixelMovementController
from .policy import EditorPolicyController
from .selection_projection import LayerSelectionProjectionCache
from .transform_interaction import (
    EditorTransformInteraction,
    SceneLayerTransformInteraction,
)

if TYPE_CHECKING:
    from ..qpane import QPane


@dataclass(frozen=True, slots=True)
class EditorRootCallbacks:
    """Facade callbacks needed by always-on editor collaborators."""

    composition_history_changed: Callable[[uuid.UUID], None]
    composition_layers_changed: Callable[[uuid.UUID], None]
    pixel_selection_changed: Callable[[PixelSelectionState], None]
    transform_changed: Callable[[], None]
    transform_preview_changed: Callable[[], None]
    raster_structure_changed: Callable[[], None]
    raster_bounds_completed: Callable[[RasterBoundsCompletion], None]
    scene_content_changed: Callable[[QRect | QRectF | None], None]
    placed_asset_changed: Callable[[uuid.UUID], None]
    pixel_move_preview_changed: Callable[[], None]
    comparison_changed: Callable[[ComparisonChange | None], None]
    active_mask_id: Callable[[], uuid.UUID | None]
    placed_asset_completed: Callable[[PlacedAssetCompletion], None]
    current_edit_scope_id: Callable[[], uuid.UUID | None]
    paint_target_changed: Callable[[PaintTargetIdentity | None], None]
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

    qpane: QPane
    state: QPaneState
    settings: Config
    executor: TaskExecutorProtocol
    cache_registry: CacheRegistry | None
    diagnostics: Diagnostics
    layer_selection: SceneLayerSelectionController
    transform_preview: SceneLayerTransformPreview
    selection_projections: LayerSelectionProjectionCache
    floating_promotions: FloatingLayerPromotionRegistry
    editor_policy: EditorPolicyController
    callbacks: EditorRootCallbacks


@dataclass(frozen=True, slots=True)
class EditorRootComponents:
    """Always-on editor collaborators installed into the QPane facade."""

    scene_providers: SceneProviderRegistry
    source_capabilities: LayerSourceCapabilities
    image_catalog: ImageCatalog
    compositions: CompositionService
    editable_raster_assets: EditableRasterAssetStore
    editable_raster_layers: EditableRasterLayerController
    placed_assets: PlacedAssetStore
    placed_asset_workflow: PlacedAssetWorkflow
    placed_asset_rasterization: PlacedAssetRasterizationService
    painting: PaintingCoordinator
    raster_paint_target: EditableRasterPaintTargetOwner
    vector: VectorDomainComponents
    pixel_selection: PixelSelectionService
    layer_assembler: CompositionLayerSceneAssembler
    view: View
    scene_mutations: SceneMutationCoordinator
    scene_movement: SceneLayerTransformController
    scene_movement_interaction: SceneLayerMovementInteraction
    scene_transform_interaction: EditorTransformInteraction
    raster_mutations: RasterLayerMutationCoordinator
    pixel_owners: LayerPixelOwnerRegistry
    pixel_mutations: LayerPixelMutationCoordinator
    editor_interaction: EditorInteractionCoordinator
    raster_floating_owner: EditableRasterFloatingLayerOwner
    selected_pixel_movement: SelectedPixelMovementController
    editor_movement_interaction: EditorMovementInteraction
    operation_resolver: EditorOperationResolver
    active_mask_coordinates: ActiveMaskLayerCoordinates
    catalog: Catalog
    composition_scene_adapter: CompositionSceneAdapter
    compare_service: CompareService
    compare_interaction: CompareDividerInteraction
    tools: Tools
    cursor_builder: CursorBuilder


class EditorCompositionRoot:
    """Own construction order and cross-domain registration for core editing."""

    def build(self, inputs: EditorRootInputs) -> EditorRootComponents:
        """Construct one complete always-on editor collaboration graph."""
        callbacks = inputs.callbacks
        scene_providers = SceneProviderRegistry()
        scene_providers.register_post_processor(inputs.transform_preview)
        source_capabilities = LayerSourceCapabilities.create()
        layer_effects = LayerEffectRenderRegistry()
        pyramid_manager = PyramidManager(
            config=inputs.settings,
            executor=inputs.executor,
            parent=inputs.qpane,
        )
        image_catalog = ImageCatalog(
            pyramid_manager=pyramid_manager,
            parent=inputs.qpane,
        )
        catalog_capabilities = CatalogSourceCapabilities(image_catalog)
        source_capabilities.metadata.register(
            CatalogImageReference, catalog_capabilities
        )
        source_capabilities.rasters.register(
            CatalogImageReference, catalog_capabilities
        )
        source_capabilities.hit_tests.register(
            CatalogImageReference, catalog_capabilities
        )

        compositions = CompositionService(
            history_changed=callbacks.composition_history_changed,
            layers_changed=callbacks.composition_layers_changed,
            catalog_size=lambda image_id: _catalog_image_size(image_catalog, image_id),
            catalog_reference=CatalogImageReference,
        )
        editable_raster_assets = EditableRasterAssetStore()
        editable_raster_presentation = EditableRasterPresentationState()
        compositions.resource_lifetime.register_owner(
            EditableRasterResourceLifecycleOwner(editable_raster_assets)
        )
        editable_raster_layers = EditableRasterLayerController(
            assets=editable_raster_assets,
            layers=compositions.layers,
            layer_edits=compositions.layer_edits,
            current_composition_id=compositions.current_composition_id,
            is_generated_default=compositions.is_generated_default,
        )
        placed_assets = PlacedAssetStore()
        compositions.resource_lifetime.register_owner(
            PlacedAssetResourceLifecycleOwner(placed_assets)
        )
        placed_history = PlacedAssetEditOwner(
            placed_assets,
            compositions.layers,
            callbacks.placed_asset_changed,
        )
        compositions.edit_controller.register_handler(
            PlacedAssetEdit,
            undo=placed_history.undo,
            redo=placed_history.redo,
        )
        placed_asset_workflow = PlacedAssetWorkflow(
            assets=placed_assets,
            layers=compositions.layers,
            layer_edits=compositions.layer_edits,
            edits=compositions.edit_controller,
            executor=inputs.executor,
            current_scope_id=compositions.current_composition_id,
            current_history_scope_id=callbacks.current_edit_scope_id,
            changed=callbacks.placed_asset_changed,
            completed=callbacks.placed_asset_completed,
        )
        placed_asset_rasterization = PlacedAssetRasterizationService(
            placed_assets=placed_assets,
            raster_assets=editable_raster_assets,
            layers=compositions.layers,
            layer_edits=compositions.layer_edits,
            executor=inputs.executor,
            changed=callbacks.placed_asset_changed,
            completed=callbacks.placed_asset_completed,
        )
        pixel_selection = PixelSelectionService(
            changed=callbacks.pixel_selection_changed,
            record_edit=compositions.edit_controller.record_applied,
        )
        compositions.edit_controller.register_handler(
            PixelSelectionEdit,
            undo=pixel_selection.undo_edit,
            redo=pixel_selection.redo_edit,
        )

        layer_assembler = CompositionLayerSceneAssembler(
            layer_instances=compositions.layers.layers_for_composition,
            layer_revision=lambda: compositions.layers.revision,
        )
        layer_assembler.register_factory(CatalogLayerDescriptorFactory(image_catalog))
        layer_assembler.register_factory(
            EditableRasterLayerDescriptorFactory(editable_raster_assets)
        )
        layer_assembler.register_factory(
            PlacedAssetLayerDescriptorFactory(placed_assets)
        )
        editable_raster_capabilities = EditableRasterSourceCapabilities(
            editable_raster_assets,
            editable_raster_presentation,
        )
        source_capabilities.metadata.register(
            EditableRasterReference, editable_raster_capabilities
        )
        source_capabilities.rasters.register(
            EditableRasterReference, editable_raster_capabilities
        )
        source_capabilities.raster_patches.register(
            EditableRasterReference, editable_raster_capabilities
        )
        source_capabilities.hit_tests.register(
            EditableRasterReference, editable_raster_capabilities
        )
        source_capabilities.pixel_presentation.register(
            EditableRasterReference, editable_raster_capabilities
        )
        placed_capabilities = PlacedAssetSourceCapabilities(placed_assets)
        source_capabilities.metadata.register(PlacedAssetReference, placed_capabilities)
        source_capabilities.rasters.register(PlacedAssetReference, placed_capabilities)
        source_capabilities.hit_tests.register(
            PlacedAssetReference, placed_capabilities
        )

        view = View(
            qpane=inputs.qpane,
            state=inputs.state,
            catalog=image_catalog,
            pyramid_manager=pyramid_manager,
            executor=inputs.executor,
            scene_providers=scene_providers,
            source_capabilities=source_capabilities,
            layer_effects=layer_effects,
        )
        scene_mutations = SceneMutationCoordinator(
            scene_provider=view.current_scene_descriptor,
            edit_controller=compositions.edit_controller,
        )
        vector = VectorDomainInstaller().install(
            compositions=compositions,
            layer_assembler=layer_assembler,
            source_capabilities=source_capabilities,
            scene_mutations=scene_mutations,
            current_history_scope_id=callbacks.current_edit_scope_id,
            changed=lambda _bounds: callbacks.vector_content_changed(),
            selection_changed=callbacks.vector_selection_changed,
            node_selection_changed=callbacks.vector_node_selection_changed,
            text_edit_changed=callbacks.vector_text_edit_changed,
            options_changed=callbacks.vector_options_changed,
            layer_selection=inputs.layer_selection,
            current_scene=view.current_scene_descriptor,
            panel_to_source=view.panel_to_layer_source_point,
            source_to_panel=view.layer_source_to_panel_point,
            raster_assets=editable_raster_assets,
            pixel_selection=pixel_selection,
            executor=inputs.executor,
            conversion_completed=callbacks.vector_conversion_completed,
            layer_effects=layer_effects,
            cache_registry=inputs.cache_registry,
        )
        view.presenter.set_vector_text_layouts(vector.text_layouts)
        pixel_owners = LayerPixelOwnerRegistry()
        scene_movement = SceneLayerTransformController(
            inputs.layer_selection,
            inputs.transform_preview,
            scene_mutations,
            pixel_owners,
        )
        scene_movement_interaction = SceneLayerMovementInteraction(
            movement=scene_movement,
            hit_test=view.scene_selection_hit_test,
            panel_to_scene=view.panel_to_scene_point,
            publish_change=callbacks.transform_changed,
            refresh_preview=callbacks.transform_preview_changed,
        )
        layer_transform_interaction = SceneLayerTransformInteraction(
            transforms=scene_movement,
            panel_to_scene=view.panel_to_scene_point,
            scene_to_panel=view.scene_to_panel_point,
            publish_change=callbacks.transform_changed,
            refresh_preview=callbacks.transform_preview_changed,
        )
        painting = PaintingCoordinator(
            scenes=scene_mutations,
            panel_to_source=view.panel_to_layer_source_point,
            source_to_panel=view.layer_source_to_panel_point,
            panel_to_scene=view.panel_to_scene_point,
            scene_to_panel=view.scene_to_panel_point,
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
        raster_paint_target = EditableRasterPaintTargetOwner(
            assets=editable_raster_assets,
            selections=pixel_selection,
            edits=compositions.edit_controller,
            changed=callbacks.scene_content_changed,
            structure_changed=callbacks.raster_structure_changed,
            presentation_state=editable_raster_presentation,
            compositor=painting.compositor,
        )
        painting.registry.register(raster_paint_target)
        painting.registry.register(
            PixelSelectionPaintTargetOwner(pixel_selection, painting.compositor)
        )
        raster_mutations = RasterLayerMutationCoordinator(view.current_scene_descriptor)
        pixel_mutations = LayerPixelMutationCoordinator(
            scene_mutations=scene_mutations,
            layer_selection=inputs.layer_selection,
            pixel_selection=pixel_selection,
            owners=pixel_owners,
            edit_controller=compositions.edit_controller,
        )
        editor_interaction = EditorInteractionCoordinator(
            active_scene=view.current_scene_descriptor,
            scene_mutations=scene_mutations,
            layer_selection=inputs.layer_selection,
            pixel_selection=pixel_selection,
            pixel_mutations=pixel_mutations,
            source_coverage=source_capabilities.coverage,
            selection_projections=inputs.selection_projections,
        )

        raster_floating_owner = EditableRasterFloatingLayerOwner(
            assets=editable_raster_assets,
            layers=compositions.layers,
            current_composition_id=compositions.current_composition_id,
            changed=callbacks.raster_structure_changed,
        )
        inputs.floating_promotions.register(raster_floating_owner)
        selected_pixel_movement = SelectedPixelMovementController(
            active_scene=view.current_scene_descriptor,
            scene_mutations=scene_mutations,
            layer_selection=inputs.layer_selection,
            pixel_selection=pixel_selection,
            pixel_owners=pixel_owners,
            edits=compositions.edit_controller,
            selection_projections=inputs.selection_projections,
            preview_changed=callbacks.pixel_move_preview_changed,
            promotions=inputs.floating_promotions,
        )
        source_operations = EditorSourceOperationRegistry()
        source_operations.register(
            PlacedAssetReference,
            EditorSourceOperations(rasterize=True),
        )
        source_operations.register(
            VectorDocumentReference,
            EditorSourceOperations(rasterize=True),
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
            paint_targets=painting.registry,
            pixel_owners=pixel_owners,
            source_operations=source_operations,
            capability_allowed=inputs.editor_policy.allows,
        )
        scene_transform_interaction = EditorTransformInteraction(
            pixels=selected_pixel_movement,
            layers=layer_transform_interaction,
            operations=operation_resolver,
        )
        editor_movement_interaction = EditorMovementInteraction(
            pixels=selected_pixel_movement,
            layers=scene_movement_interaction,
            operations=operation_resolver,
            panel_to_scene=view.panel_to_scene_point,
            refresh_preview=callbacks.pixel_move_preview_changed,
        )
        view.presenter.set_pixel_move_preview_provider(
            lambda: selected_pixel_movement.raster_preview
        )
        active_mask_coordinates = ActiveMaskLayerCoordinates(
            active_mask_id=callbacks.active_mask_id,
            active_scene=view.coordinate_scene_descriptor,
            panel_to_scene=view.panel_to_scene_point,
            layer_to_panel=view.layer_source_to_panel_point,
        )

        catalog = Catalog(
            catalog=image_catalog,
            controller=view.catalog_controller,
            link_manager=view.link_manager,
            swap_delegate=view.swap_delegate,
            qpane=inputs.qpane,
        )
        scene_mutations.register_owner(CatalogLayerMutationOwner(compositions))
        scene_mutations.register_owner(
            EditableRasterSceneMutationOwner(
                compositions.layers,
                compositions.current_composition_id,
            )
        )
        scene_mutations.register_owner(
            PlacedAssetSceneMutationOwner(
                compositions.layers,
                compositions.layer_edits,
                compositions.current_composition_id,
            )
        )
        raster_mutations.register_owner(
            EditableRasterStructureMutationOwner(
                editable_raster_assets,
                edits=compositions.edit_controller,
                executor=inputs.executor,
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
        )
        scene_providers.register_replacement(composition_scene_adapter)
        compare_service = CompareService(
            catalog=image_catalog,
            compositions=compositions,
            changed_callback=callbacks.comparison_changed,
        )
        compare_interaction = CompareDividerInteraction(
            qpane=inputs.qpane,
            service=compare_service,
        )
        scene_providers.register_geometry_adapter(compare_service)
        scene_providers.register_contribution(compare_service)

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
            source_capabilities=source_capabilities,
            image_catalog=image_catalog,
            compositions=compositions,
            editable_raster_assets=editable_raster_assets,
            editable_raster_layers=editable_raster_layers,
            placed_assets=placed_assets,
            placed_asset_workflow=placed_asset_workflow,
            placed_asset_rasterization=placed_asset_rasterization,
            painting=painting,
            raster_paint_target=raster_paint_target,
            vector=vector,
            pixel_selection=pixel_selection,
            layer_assembler=layer_assembler,
            view=view,
            scene_mutations=scene_mutations,
            scene_movement=scene_movement,
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
            active_mask_coordinates=active_mask_coordinates,
            catalog=catalog,
            composition_scene_adapter=composition_scene_adapter,
            compare_service=compare_service,
            compare_interaction=compare_interaction,
            tools=tools,
            cursor_builder=cursor_builder,
        )


def _catalog_image_size(catalog: ImageCatalog, image_id: uuid.UUID) -> QSize:
    """Return one catalog image's detached size or an empty size when absent."""
    image = catalog.getImage(image_id)
    return QSize() if image is None or image.isNull() else QSize(image.size())
