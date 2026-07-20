#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Install the vector domain through focused composition capabilities."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRect, QRectF

from ..cache.registry import CacheRegistry
from ..composition import CompositionService
from ..concurrency import TaskExecutorProtocol
from ..raster.assets import EditableRasterAssetStore
from ..scene.effects import LayerEffectRenderRegistry
from ..scene.layer_assembly import CompositionLayerSceneAssembler
from ..scene.layer_selection import SceneLayerSelectionController
from ..scene.model import SceneDescriptor
from ..scene.mutations import SceneMutationCoordinator
from ..scene.source_capabilities import LayerSourceCapabilities
from ..selection import PixelSelectionService
from .conversion import VectorConversionCompletion, VectorConversionService
from .descriptor_factory import VectorLayerDescriptorFactory
from .editing import VectorEditService
from .effects import VectorMaskController, VectorMaskEffect, VectorMaskRenderOwner
from .interaction import VectorInteractionController
from .layers import VectorLayerController, VectorSceneMutationOwner
from .mask_cache import VectorMaskPathCache
from .node_edit import VectorNodeEditController
from .projection import VectorDocumentProjection
from .resource_lifecycle import VectorResourceLifecycleOwner
from .selection import VectorObjectSelectionController
from .source_capabilities import VectorSourceCapabilities
from .source_reference import VectorDocumentReference
from .store import VectorAssetStore
from .targets import VectorAuthoringTargetResolver
from .text_edit import VectorTextEditController
from .text_layout import SemanticTextLayoutCache


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
        layer_assembler: CompositionLayerSceneAssembler,
        source_capabilities: LayerSourceCapabilities,
        scene_mutations: SceneMutationCoordinator,
        current_history_scope_id: Callable[[], uuid.UUID | None],
        changed: Callable[[QRect | QRectF | None], None],
        selection_changed: Callable[[], None],
        node_selection_changed: Callable[[], None],
        text_edit_changed: Callable[[], None],
        options_changed: Callable[[], None],
        layer_selection: SceneLayerSelectionController,
        current_scene: Callable[[], SceneDescriptor | None],
        panel_to_source: Callable[
            [uuid.UUID, uuid.UUID, QPointF],
            QPointF | None,
        ],
        source_to_panel: Callable[
            [uuid.UUID, uuid.UUID, QPointF],
            QPointF | None,
        ],
        raster_assets: EditableRasterAssetStore,
        pixel_selection: PixelSelectionService,
        executor: TaskExecutorProtocol,
        conversion_completed: Callable[[VectorConversionCompletion], None],
        layer_effects: LayerEffectRenderRegistry,
        cache_registry: CacheRegistry | None,
    ) -> VectorDomainComponents:
        """Create vector owners and register each focused external capability."""
        assets = VectorAssetStore()
        projection = VectorDocumentProjection(assets)
        text_layouts = SemanticTextLayoutCache()
        if cache_registry is not None:
            cache_registry.attach_text_layout_cache(text_layouts)
        compositions.resource_lifetime.register_owner(
            VectorResourceLifecycleOwner(assets)
        )
        layers = VectorLayerController(
            assets=assets,
            layers=compositions.layers,
            layer_edits=compositions.layer_edits,
            current_composition_id=compositions.current_composition_id,
            current_history_scope_id=current_history_scope_id,
        )
        layer_assembler.register_factory(VectorLayerDescriptorFactory(projection))
        capabilities = VectorSourceCapabilities(assets, projection, text_layouts)
        source_capabilities.metadata.register(
            VectorDocumentReference,
            capabilities,
        )
        source_capabilities.vectors.register(
            VectorDocumentReference,
            capabilities,
        )
        source_capabilities.hit_tests.register(
            VectorDocumentReference,
            capabilities,
        )
        scene_mutations.register_owner(
            VectorSceneMutationOwner(
                compositions.layers,
                compositions.current_composition_id,
            )
        )
        edits = VectorEditService(
            assets=assets,
            edits=compositions.edit_controller,
            changed=lambda _vector_id: changed(None),
        )
        selection = VectorObjectSelectionController(selection_changed)
        targets = VectorAuthoringTargetResolver(
            assets=assets,
            layers=compositions.layers,
            current_composition_id=compositions.current_composition_id,
            current_scene=current_scene,
            panel_to_source=panel_to_source,
            source_to_panel=source_to_panel,
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
            panel_to_source=panel_to_source,
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
            executor=executor,
            changed=lambda: changed(None),
            completed=conversion_completed,
        )
        mask_paths = VectorMaskPathCache(text_layouts=text_layouts)
        if cache_registry is not None:
            cache_registry.attach_vector_mask_cache(mask_paths)
        layer_effects.register(
            VectorMaskEffect,
            VectorMaskRenderOwner(projection, mask_paths),
        )
        masks = VectorMaskController(
            assets=assets,
            layers=compositions.layers,
            layer_edits=compositions.layer_edits,
        )
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
