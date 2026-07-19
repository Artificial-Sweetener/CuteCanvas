#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Mask-domain ownership of floating fragment layer promotion."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtGui import QColor

from ..composition.layers import (
    CompositionLayerInstance,
    CompositionLayerSourceKind,
    ImageSceneLayerStore,
)
from ..coverage import CoverageSnapshot
from ..editor.floating_layers import FloatingLayerTransition
from ..scene.identity import mask_layer_id
from ..scene.model import LayerDescriptor, SceneDescriptor
from ..scene.pixel_fragments import RasterPixelFormat, RasterPixelFragment
from .mask import MaskAssetStore


@dataclass(frozen=True, slots=True)
class MaskPromotionState:
    """Retain one mask asset and composition instance."""

    image_id: uuid.UUID
    instance: CompositionLayerInstance
    snapshot: CoverageSnapshot


class MaskFloatingLayerOwner:
    """Create and replay mask layers from floating scalar fragments."""

    owner_key = "mask"

    def __init__(
        self,
        *,
        assets: MaskAssetStore,
        layers: ImageSceneLayerStore,
        current_image_id: Callable[[], uuid.UUID | None],
        changed: Callable[[uuid.UUID], None],
    ) -> None:
        """Bind mask assets, composition instances, and publication."""
        self._assets = assets
        self._layers = layers
        self._current_image_id = current_image_id
        self._changed = changed

    def accepts_fragment(self, fragment: RasterPixelFragment) -> bool:
        """Accept scalar mask fragments."""
        return fragment.pixel_format is RasterPixelFormat.COVERAGE8

    def promote(
        self,
        *,
        scene: SceneDescriptor,
        source_layer: LayerDescriptor,
        fragment: RasterPixelFragment,
        delta: tuple[int, int],
        label: str | None,
    ) -> FloatingLayerTransition | None:
        """Create one composition-owned mask layer."""
        image_id = self._current_image_id()
        transform = source_layer.transform
        source_instance = (
            None
            if image_id is None
            else self._layers.layer(image_id, source_layer.layer_id)
        )
        if (
            image_id is None
            or transform is None
            or source_instance is None
            or not self.accepts_fragment(fragment)
        ):
            return None
        mask_id = uuid.uuid4()
        layer_id = mask_layer_id(scene.scene_id, mask_id)
        snapshot = CoverageSnapshot(
            fragment.bounds,
            fragment.coverage.extent_policy,
            fragment.materialized_pixels(),
        )
        instance = CompositionLayerInstance(
            layer_id=layer_id,
            source_kind=CompositionLayerSourceKind.MASK,
            source_id=mask_id,
            transform=transform.translated(
                delta[0] * transform.scale_x,
                delta[1] * transform.scale_y,
            ),
            visible=True,
            opacity=source_layer.opacity,
            tint=(
                QColor(source_instance.tint)
                if source_instance.tint is not None
                else QColor(0, 220, 180)
            ),
            hit_test=True,
            interaction=source_layer.interaction,
            role="mask",
            label=label or source_layer.label or "Floating mask",
        )
        state = MaskPromotionState(image_id, instance, snapshot)
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
        """Return whether the promoted mask is present or absent as expected."""
        state = self._state(transition)
        if state is None:
            return False
        asset_present = self._assets.get_layer(state.instance.source_id) is not None
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
        """Restore promoted mask presence transactionally."""
        state = self._state(transition)
        if state is None:
            return False
        if self.matches(transition, use_after=use_after):
            return True
        mask_id = state.instance.source_id
        if use_after:
            if self._assets.get_layer(mask_id) is not None:
                return False
            self._assets.restore_mask(mask_id, state.snapshot)
            if not self._layers.add_layer(state.image_id, state.instance):
                self._assets.delete_mask(mask_id)
                return False
        else:
            if not self.matches(transition, use_after=True):
                return False
            if not self._layers.remove_layer(state.image_id, state.instance.layer_id):
                return False
            if not self._assets.delete_mask(mask_id):
                self._layers.add_layer(state.image_id, state.instance)
                return False
        self._changed(mask_id)
        return True

    def _state(
        self,
        transition: FloatingLayerTransition,
    ) -> MaskPromotionState | None:
        """Return validated mask-specific transition state."""
        return (
            transition.state
            if transition.owner_key == self.owner_key
            and isinstance(transition.state, MaskPromotionState)
            else None
        )
