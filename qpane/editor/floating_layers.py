#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Source-domain routing for floating fragment layer promotion."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from ..scene.affine import LayerTransform
from ..scene.model import LayerDescriptor, SceneDescriptor
from ..scene.pixel_fragments import RasterPixelFragment
from ..scene.source_references import LayerSourceReference


@dataclass(frozen=True, slots=True)
class FloatingLayerTransition:
    """Retain opaque source-domain state for one created composition layer."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    owner_key: str
    state: object
    retained_bytes: int
    transform: LayerTransform
    resources: tuple[LayerSourceReference, ...] = ()

    def __post_init__(self) -> None:
        """Validate bounded history accounting."""
        if self.retained_bytes < 0:
            raise ValueError("floating layer retained bytes must be non-negative")
        object.__setattr__(self, "resources", tuple(self.resources))
        if not all(
            isinstance(source, LayerSourceReference) for source in self.resources
        ):
            raise TypeError("floating layer resources must be source references")


class FloatingLayerPromotionOwner(Protocol):
    """Source domain capable of creating and replaying a fragment layer."""

    owner_key: str

    def accepts_fragment(self, fragment: RasterPixelFragment) -> bool:
        """Return whether this domain can create a layer for ``fragment``."""
        ...

    def promote(
        self,
        *,
        scene: SceneDescriptor,
        source_layer: LayerDescriptor,
        fragment: RasterPixelFragment,
        transform: LayerTransform,
        label: str | None,
    ) -> FloatingLayerTransition | None:
        """Create a layer and return exact state for undo and redo."""
        ...

    def matches(
        self,
        transition: FloatingLayerTransition,
        *,
        use_after: bool,
    ) -> bool:
        """Return whether layer lifecycle matches one transition side."""
        ...

    def restore(
        self,
        transition: FloatingLayerTransition,
        *,
        use_after: bool,
    ) -> bool:
        """Restore absent or present layer state exactly."""
        ...


class FloatingLayerPromotionRegistry:
    """Own unique source-domain routes for floating layer creation."""

    def __init__(self) -> None:
        """Initialize an empty owner registry."""
        self._owners: dict[str, FloatingLayerPromotionOwner] = {}

    def register(self, owner: FloatingLayerPromotionOwner) -> None:
        """Register one owner key exactly once."""
        existing = self._owners.get(owner.owner_key)
        if existing is not None and existing is not owner:
            raise ValueError(
                f"floating layer owner already registered: {owner.owner_key}"
            )
        self._owners[owner.owner_key] = owner

    def unregister(self, owner: FloatingLayerPromotionOwner) -> None:
        """Remove one owner by identity."""
        if self._owners.get(owner.owner_key) is owner:
            self._owners.pop(owner.owner_key)

    def owner_for_fragment(
        self,
        fragment: RasterPixelFragment,
    ) -> FloatingLayerPromotionOwner | None:
        """Return the sole owner accepting a fragment format."""
        return next(
            (
                owner
                for owner in self._owners.values()
                if owner.accepts_fragment(fragment)
            ),
            None,
        )

    def owner_for_transition(
        self,
        transition: FloatingLayerTransition,
    ) -> FloatingLayerPromotionOwner | None:
        """Return the owner named by retained lifecycle state."""
        return self._owners.get(transition.owner_key)
