#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Generic routing for raster-source state and structural mutations."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from .model import LayerDescriptor, SceneDescriptor
from .raster import RasterBounds, RasterExtentPolicy


@dataclass(frozen=True, slots=True)
class RasterLayerState:
    """Describe authoritative raster storage for one resolved scene layer."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    bounds: RasterBounds
    extent_policy: RasterExtentPolicy
    content_revision: int
    structure_revision: int
    pending_request_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class RasterBoundsCompletion:
    """Describe the terminal result of an asynchronous bounds request."""

    request_id: uuid.UUID
    scene_id: uuid.UUID
    layer_id: uuid.UUID
    succeeded: bool
    message: str = ""


class RasterLayerMutationOwner(Protocol):
    """Source-domain owner for raster state, policy, and storage bounds."""

    def supports_layer(self, layer: LayerDescriptor) -> bool:
        """Return whether this owner controls ``layer``'s raster source."""
        ...

    def state(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
    ) -> RasterLayerState | None:
        """Return current authoritative raster state."""
        ...

    def set_extent_policy(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        policy: RasterExtentPolicy,
    ) -> bool:
        """Replace the source-owned write extent policy."""
        ...

    def request_bounds(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
        bounds: RasterBounds,
        is_current: Callable[[], bool],
    ) -> uuid.UUID | None:
        """Schedule a source-owned storage-bounds transition."""
        ...

    def shutdown(self) -> None:
        """Cancel pending work and release worker callbacks."""
        ...


class RasterLayerMutationCoordinator:
    """Resolve generic scene/layer requests to raster source-domain owners."""

    def __init__(
        self,
        scene_provider: Callable[[], SceneDescriptor | None],
    ) -> None:
        """Bind the active scene provider without assuming source kinds."""
        self._scene_provider = scene_provider
        self._owners: list[RasterLayerMutationOwner] = []

    def register_owner(
        self,
        owner: RasterLayerMutationOwner,
    ) -> RasterLayerMutationOwner:
        """Register one source-domain owner when it is not already present."""
        if owner not in self._owners:
            self._owners.append(owner)
        return owner

    def unregister_owner(self, owner: RasterLayerMutationOwner) -> None:
        """Cancel and remove one source-domain owner."""
        if owner in self._owners:
            self._owners.remove(owner)
            owner.shutdown()

    def state(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> RasterLayerState | None:
        """Return raster state for an active scene layer when supported."""
        resolved = self._resolve(scene_id, layer_id)
        if resolved is None:
            return None
        scene, layer, owner = resolved
        return owner.state(scene, layer)

    def set_extent_policy(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        policy: RasterExtentPolicy,
    ) -> bool:
        """Route a validated extent-policy change to the source owner."""
        resolved = self._resolve(scene_id, layer_id)
        if resolved is None:
            return False
        scene, layer, owner = resolved
        return owner.set_extent_policy(scene, layer, RasterExtentPolicy(policy))

    def request_bounds(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        bounds: RasterBounds,
    ) -> uuid.UUID | None:
        """Route an asynchronous storage-bounds request to the source owner."""
        resolved = self._resolve(scene_id, layer_id)
        if resolved is None:
            return None
        scene, layer, owner = resolved
        source = layer.source
        return owner.request_bounds(
            scene,
            layer,
            bounds,
            lambda: self._target_is_current(scene_id, layer_id, source, owner),
        )

    def shutdown(self) -> None:
        """Cancel all source work and forget registered owners."""
        owners, self._owners = self._owners, []
        for owner in owners:
            owner.shutdown()

    def _resolve(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> tuple[SceneDescriptor, LayerDescriptor, RasterLayerMutationOwner] | None:
        """Resolve identifiers against the active scene and first supporting owner."""
        if not isinstance(scene_id, uuid.UUID) or not isinstance(layer_id, uuid.UUID):
            return None
        scene = self._scene_provider()
        if scene is None or scene.scene_id != scene_id:
            return None
        layer = next(
            (candidate for candidate in scene.layers if candidate.layer_id == layer_id),
            None,
        )
        if layer is None:
            return None
        owner = next(
            (
                candidate
                for candidate in self._owners
                if candidate.supports_layer(layer)
            ),
            None,
        )
        if owner is None:
            return None
        return scene, layer, owner

    def _target_is_current(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        source: object,
        owner: RasterLayerMutationOwner,
    ) -> bool:
        """Return whether an async result still targets the resolved source instance."""
        resolved = self._resolve(scene_id, layer_id)
        if resolved is None:
            return False
        _scene, layer, current_owner = resolved
        return current_owner is owner and layer.source == source
