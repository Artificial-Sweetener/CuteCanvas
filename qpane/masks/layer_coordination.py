#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Mask layer-instance ownership and scene mutation coordination."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor

from ..composition.layers import (
    CompositionLayerInstance,
    CompositionLayerSourceKind,
    ImageSceneLayerStore,
)
from ..composition.mutations import ImageSceneMaskMutationOwner
from ..scene.identity import default_scene_id, mask_layer_id
from ..scene.model import (
    LayerDescriptor,
    LayerInteractionPolicy,
    LayerKind,
    LayerPlacement,
    SceneDescriptor,
)
from ..scene.mutations import SceneMutationCoordinator
from ..scene.sources import MaskLayerSource
from .mask import MaskAssetStore
from .mask_controller import MaskController


class MaskLayerCoordinator:
    """Own mask layer instances and their scene mutation routing."""

    def __init__(
        self,
        *,
        layers: ImageSceneLayerStore,
        assets: MaskAssetStore,
        controller: MaskController,
        current_image_id: Callable[[], uuid.UUID | None],
        remove_mask: Callable[[uuid.UUID, uuid.UUID], bool],
    ) -> None:
        """Bind composition, asset, render, and host lifecycle collaborators."""
        self._layers = layers
        self._assets = assets
        self._controller = controller
        self._current_image_id = current_image_id
        self._remove_mask = remove_mask
        self._scene_mutations: SceneMutationCoordinator | None = None
        self._scene_mutation_owner: ImageSceneMaskMutationOwner | None = None

    @property
    def store(self) -> ImageSceneLayerStore:
        """Return the authoritative composition layer store."""
        return self._layers

    def mask_ids_for_image(self, image_id: uuid.UUID) -> list[uuid.UUID]:
        """Return mask asset IDs in composition-owned z-order."""
        return [
            instance.source_id
            for instance in self._layers.layers_for_image(image_id)
            if instance.source_kind == CompositionLayerSourceKind.MASK
        ]

    def image_ids_for_mask(self, mask_id: uuid.UUID) -> tuple[uuid.UUID, ...]:
        """Return image scenes containing an instance of one mask asset."""
        return self._layers.image_ids_for_source(
            CompositionLayerSourceKind.MASK,
            mask_id,
        )

    def instances_for_image(
        self, image_id: uuid.UUID
    ) -> tuple[CompositionLayerInstance, ...]:
        """Return the complete composition-owned image scene stack."""
        return self._layers.layers_for_image(image_id)

    def instance_for_mask(
        self,
        mask_id: uuid.UUID,
        image_id: uuid.UUID | None = None,
    ) -> CompositionLayerInstance | None:
        """Return one presentation instance for a mask asset."""
        resolved_image_id = image_id or self._current_image_id()
        if resolved_image_id is not None:
            instance = self._layers.layer_for_source(
                resolved_image_id,
                CompositionLayerSourceKind.MASK,
                mask_id,
            )
            if instance is not None:
                return instance
        image_ids = self.image_ids_for_mask(mask_id)
        if not image_ids:
            return None
        return self._layers.layer_for_source(
            image_ids[0],
            CompositionLayerSourceKind.MASK,
            mask_id,
        )

    def color(self, mask_id: uuid.UUID) -> QColor | None:
        """Return the composition-owned tint for one mask instance."""
        instance = self.instance_for_mask(mask_id)
        if instance is None or instance.tint is None:
            return None
        return QColor(instance.tint)

    def attach(
        self,
        mask_id: uuid.UUID,
        image_id: uuid.UUID,
        *,
        color: QColor,
        opacity: float = 0.5,
    ) -> bool:
        """Create a mask layer instance without transferring asset ownership."""
        asset = self._assets.get_layer(mask_id)
        if asset is None or asset.mask_image.isNull():
            return False
        placement = LayerPlacement(
            0.0,
            0.0,
            float(asset.mask_image.width()),
            float(asset.mask_image.height()),
        )
        if not self._layers.layers_for_image(image_id):
            self._layers.ensure_image(image_id, placement)
        return self._layers.add_layer(
            image_id,
            CompositionLayerInstance(
                layer_id=mask_layer_id(default_scene_id(image_id), mask_id),
                source_kind=CompositionLayerSourceKind.MASK,
                source_id=mask_id,
                placement=placement,
                opacity=opacity,
                tint=color,
                hit_test=True,
                interaction=LayerInteractionPolicy(),
                role="mask",
            ),
        )

    def remove(self, image_id: uuid.UUID, mask_id: uuid.UUID) -> bool:
        """Remove one mask instance and prune its asset only when orphaned."""
        instance = self._layers.layer_for_source(
            image_id,
            CompositionLayerSourceKind.MASK,
            mask_id,
        )
        if instance is None or not self._layers.remove_layer(
            image_id, instance.layer_id
        ):
            return False
        if not self.image_ids_for_mask(mask_id):
            self._assets.delete_mask(mask_id)
        return True

    def reorder_mask_slot(
        self,
        image_id: uuid.UUID,
        mask_id: uuid.UUID,
        target_mask_index: int,
    ) -> bool:
        """Move a mask to another mask slot while preserving other layer kinds."""
        layers = self._layers.layers_for_image(image_id)
        mask_positions = [
            index
            for index, instance in enumerate(layers)
            if instance.source_kind == CompositionLayerSourceKind.MASK
        ]
        instance = self._layers.layer_for_source(
            image_id,
            CompositionLayerSourceKind.MASK,
            mask_id,
        )
        if (
            instance is None
            or target_mask_index < 0
            or target_mask_index >= len(mask_positions)
        ):
            return False
        return self._layers.reorder_layer(
            image_id,
            instance.layer_id,
            mask_positions[target_mask_index],
        )

    def scene_provider_revision(self) -> tuple[object, ...]:
        """Return mask order and render revisions for scene compilation."""
        image_id = self._current_image_id()
        if image_id is None:
            return (None, ())
        mask_revisions = tuple(
            (
                mask_id,
                self._controller.renders.render_revision(mask_id),
            )
            for mask_id in self.mask_ids_for_image(image_id)
        )
        return (image_id, self._layers.revision, mask_revisions)

    def set_scene_mutation_coordinator(
        self, coordinator: SceneMutationCoordinator | None
    ) -> None:
        """Register mask layer mutations with the internal scene coordinator."""
        if self._scene_mutation_owner is not None and self._scene_mutations is not None:
            self._scene_mutations.unregister_owner(self._scene_mutation_owner)
        self._scene_mutations = coordinator
        self._scene_mutation_owner = None
        if coordinator is None:
            return
        owner = ImageSceneMaskMutationOwner(
            self._layers,
            self._current_image_id,
            remove_mask=self._remove_mask,
            notify_mask_opacity=self._controller.renders.notify_opacity_changed,
            request_mask_revision=lambda mask_id, reason: self.apply_revision_request(
                mask_id,
                reason=reason,
            ),
        )
        coordinator.register_owner(owner)
        self._scene_mutation_owner = owner

    def apply_revision_request(self, mask_id: uuid.UUID, *, reason: str) -> bool:
        """Apply a validated source revision request for a mask layer."""
        if self._assets.get_layer(mask_id) is None:
            return False
        self._controller.edits.advance_epoch(mask_id, reason=reason)
        self._controller.renders.invalidate(mask_id, reason=reason)
        self._controller.renders.warm(mask_id)
        self._controller.mask_updated.emit(mask_id, QRect())
        return True

    def route_reorder(self, mask_id: uuid.UUID, target_scene_index: int) -> bool | None:
        """Route mask reordering through the scene coordinator when possible."""
        coordinator = self._scene_mutations
        scene_layer = self._scene_layer_for_mask(mask_id)
        if coordinator is None or scene_layer is None:
            return None
        scene, layer = scene_layer
        result = coordinator.reorder_layer(
            scene.scene_id,
            layer.layer_id,
            target_scene_index,
        )
        return result.changed if result.accepted else False

    def route_opacity(self, mask_id: uuid.UUID, opacity: float) -> bool | None:
        """Route mask opacity updates through the scene coordinator when possible."""
        coordinator = self._scene_mutations
        scene_layer = self._scene_layer_for_mask(mask_id)
        if coordinator is None or scene_layer is None:
            return None
        scene, layer = scene_layer
        result = coordinator.set_opacity(scene.scene_id, layer.layer_id, opacity)
        return result.changed if result.accepted else False

    def update_presentation(
        self,
        mask_id: uuid.UUID,
        *,
        color: QColor | None = None,
        opacity: float | None = None,
    ) -> bool:
        """Update composition-owned presentation for every mask instance."""
        if self._assets.get_layer(mask_id) is None:
            return False
        changed = False
        if color is not None:
            color_changed = False
            for image_id in self.image_ids_for_mask(mask_id):
                instance = self._layers.layer_for_source(
                    image_id,
                    CompositionLayerSourceKind.MASK,
                    mask_id,
                )
                if instance is not None:
                    color_changed = (
                        self._layers.update_presentation(
                            image_id,
                            instance.layer_id,
                            tint=color,
                        )
                        or color_changed
                    )
            if color_changed:
                self._controller.renders.notify_color_changed(mask_id)
            changed = color_changed
        if opacity is not None:
            opacity_changed = self.route_opacity(mask_id, opacity)
            if opacity_changed is None:
                opacity_changed = False
                for image_id in self.image_ids_for_mask(mask_id):
                    instance = self._layers.layer_for_source(
                        image_id,
                        CompositionLayerSourceKind.MASK,
                        mask_id,
                    )
                    if instance is not None:
                        opacity_changed = (
                            self._layers.update_presentation(
                                image_id,
                                instance.layer_id,
                                opacity=opacity,
                            )
                            or opacity_changed
                        )
                if opacity_changed:
                    self._controller.renders.notify_opacity_changed(mask_id)
            changed = opacity_changed or changed
        return changed

    def mask_stack_end_index(self, *, forward: bool) -> int | None:
        """Return the scene index used to rotate mask order."""
        scene = (
            self._scene_mutations.active_scene()
            if self._scene_mutations is not None
            else None
        )
        if scene is None:
            return None
        mask_indexes = [
            index
            for index, layer in enumerate(scene.layers)
            if layer.kind == LayerKind.MASK
        ]
        if not mask_indexes:
            return None
        return mask_indexes[-1] if forward else mask_indexes[0]

    def _scene_layer_for_mask(
        self, mask_id: uuid.UUID
    ) -> tuple[SceneDescriptor, LayerDescriptor] | None:
        """Return the active scene/layer pair for mask_id when visible."""
        if self._scene_mutations is None:
            return None
        return self._scene_mutations.find_layer(
            lambda layer: isinstance(layer.source, MaskLayerSource)
            and layer.source.mask_id == mask_id
        )
