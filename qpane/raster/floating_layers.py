#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Editable-RGBA ownership of floating fragment layer promotion."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from ..composition.layers import (
    CompositionLayerInstance,
    CompositionLayerSourceKind,
    ImageSceneLayerStore,
)
from ..editor.floating_layers import FloatingLayerTransition
from ..scene.identity import editable_raster_layer_id
from ..scene.model import LayerDescriptor, SceneDescriptor
from ..scene.pixel_fragments import RasterPixelFormat, RasterPixelFragment
from .assets import EditableRasterAssetStore
from .color_surface import ColorRasterSnapshot


@dataclass(frozen=True, slots=True)
class EditableRasterPromotionState:
    """Retain one editable raster asset and composition instance."""

    image_id: uuid.UUID
    instance: CompositionLayerInstance
    snapshot: ColorRasterSnapshot


class EditableRasterFloatingLayerOwner:
    """Create and replay editable RGBA layers from floating fragments."""

    owner_key = "editable-raster"

    def __init__(
        self,
        *,
        assets: EditableRasterAssetStore,
        layers: ImageSceneLayerStore,
        current_image_id: Callable[[], uuid.UUID | None],
        changed: Callable[[], None],
    ) -> None:
        """Bind raster assets, composition instances, and publication."""
        self._assets = assets
        self._layers = layers
        self._current_image_id = current_image_id
        self._changed = changed

    def accepts_fragment(self, fragment: RasterPixelFragment) -> bool:
        """Accept premultiplied color fragments."""
        return fragment.pixel_format is RasterPixelFormat.PREMULTIPLIED_ARGB32

    def promote(
        self,
        *,
        scene: SceneDescriptor,
        source_layer: LayerDescriptor,
        fragment: RasterPixelFragment,
        delta: tuple[int, int],
        label: str | None,
    ) -> FloatingLayerTransition | None:
        """Create one composition-owned editable raster layer."""
        image_id = self._current_image_id()
        transform = source_layer.transform
        if image_id is None or transform is None or not self.accepts_fragment(fragment):
            return None
        raster_id = uuid.uuid4()
        layer_id = editable_raster_layer_id(scene.scene_id, raster_id)
        snapshot = ColorRasterSnapshot(
            fragment.bounds,
            fragment.coverage.extent_policy,
            fragment.materialized_pixels(),
        )
        instance = CompositionLayerInstance(
            layer_id=layer_id,
            source_kind=CompositionLayerSourceKind.RASTER,
            source_id=raster_id,
            transform=transform.translated(
                delta[0] * transform.scale_x,
                delta[1] * transform.scale_y,
            ),
            visible=True,
            opacity=source_layer.opacity,
            interaction=source_layer.interaction,
            role="raster",
            label=label or source_layer.label or "Floating raster",
        )
        state = EditableRasterPromotionState(image_id, instance, snapshot)
        transition = FloatingLayerTransition(
            scene.scene_id,
            layer_id,
            self.owner_key,
            state,
            snapshot.pixels.nbytes,
            instance.transform,
        )
        return transition if self.restore(transition, use_after=True) else None

    def matches(
        self,
        transition: FloatingLayerTransition,
        *,
        use_after: bool,
    ) -> bool:
        """Return whether the promoted raster is present or absent as expected."""
        state = self._state(transition)
        if state is None:
            return False
        asset_present = self._assets.get(state.instance.source_id) is not None
        instance = self._layers.layer(state.image_id, state.instance.layer_id)
        return (
            asset_present and instance == state.instance
            if use_after
            else not asset_present and instance is None
        )

    def restore(
        self,
        transition: FloatingLayerTransition,
        *,
        use_after: bool,
    ) -> bool:
        """Restore promoted raster presence transactionally."""
        state = self._state(transition)
        if state is None:
            return False
        if self.matches(transition, use_after=use_after):
            return True
        if use_after:
            if self._assets.get(state.instance.source_id) is not None:
                return False
            self._assets.restore(state.instance.source_id, state.snapshot)
            if not self._layers.add_layer(state.image_id, state.instance):
                self._assets.remove(state.instance.source_id)
                return False
        else:
            if not self.matches(transition, use_after=True):
                return False
            if not self._layers.remove_layer(state.image_id, state.instance.layer_id):
                return False
            if not self._assets.remove(state.instance.source_id):
                self._layers.add_layer(state.image_id, state.instance)
                return False
        self._changed()
        return True

    def _state(
        self,
        transition: FloatingLayerTransition,
    ) -> EditableRasterPromotionState | None:
        """Return validated raster-specific transition state."""
        return (
            transition.state
            if transition.owner_key == self.owner_key
            and isinstance(transition.state, EditableRasterPromotionState)
            else None
        )
