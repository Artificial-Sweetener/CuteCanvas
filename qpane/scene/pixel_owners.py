#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Authoritative routing for source-owned editable raster pixels."""

from __future__ import annotations

from typing import Protocol

import numpy as np

from ..coverage import CoverageSnapshot
from .model import LayerDescriptor, SceneDescriptor
from .pixel_fragments import RasterPixelFragment, RasterPixelLift
from .pixel_transitions import RasterPixelTransition
from .raster import RasterBounds, RasterExtentPolicy


class LayerPixelMutationOwner(Protocol):
    """Source domain capable of patch-based raster mutation and restoration."""

    def supports_layer(self, scene: SceneDescriptor, layer: LayerDescriptor) -> bool:
        """Return whether this owner owns editable pixels for ``layer``."""
        ...

    def extent_policy(self, layer: LayerDescriptor) -> RasterExtentPolicy | None:
        """Return the authoritative raster extent policy for ``layer``."""
        ...

    def content_coverage(
        self,
        layer: LayerDescriptor,
        bounds: RasterBounds,
    ) -> CoverageSnapshot | None:
        """Return binary occupancy for meaningful source pixels in ``bounds``."""
        ...

    def content_bounds(self, layer: LayerDescriptor) -> RasterBounds | None:
        """Return the smallest local bounds containing meaningful pixels."""
        ...

    def capture_patch(
        self,
        layer: LayerDescriptor,
        bounds: RasterBounds,
    ) -> np.ndarray | None:
        """Return detached source pixels for one local patch."""
        ...

    def clear_coverage(
        self,
        layer: LayerDescriptor,
        coverage: CoverageSnapshot,
    ) -> bool:
        """Clear source pixels proportionally to local coverage."""
        ...

    def restore_patch(
        self,
        layer: LayerDescriptor,
        bounds: RasterBounds,
        pixels: np.ndarray,
    ) -> bool:
        """Restore detached pixels into one source-local patch."""
        ...

    def move_coverage(
        self,
        layer: LayerDescriptor,
        coverage: CoverageSnapshot,
        delta_x: int,
        delta_y: int,
    ) -> RasterPixelTransition | None:
        """Move selected pixels and return the exact applied transition."""
        ...

    def lift_coverage(
        self,
        layer: LayerDescriptor,
        coverage: CoverageSnapshot,
    ) -> RasterPixelLift | None:
        """Capture a reversible source extraction without applying it."""
        ...

    def preview_move(
        self,
        layer: LayerDescriptor,
        lift: RasterPixelLift,
        delta_x: int,
        delta_y: int,
        *,
        cut_source: bool,
    ) -> RasterPixelTransition | None:
        """Compose an exact movement transition without mutating source pixels."""
        ...

    def place_fragment(
        self,
        layer: LayerDescriptor,
        fragment: RasterPixelFragment,
        destination: RasterBounds,
    ) -> RasterPixelTransition | None:
        """Composite a compatible fragment at destination and return its transition."""
        ...

    def accepts_fragment(
        self,
        layer: LayerDescriptor,
        fragment: RasterPixelFragment,
    ) -> bool:
        """Return whether ``layer`` can accept this fragment format."""
        ...

    def transition_matches(
        self,
        layer: LayerDescriptor,
        transition: RasterPixelTransition,
        *,
        use_after: bool,
    ) -> bool:
        """Return whether current pixels equal one side of a retained transition."""
        ...

    def restore_transition(
        self,
        layer: LayerDescriptor,
        transition: RasterPixelTransition,
        *,
        use_after: bool,
    ) -> bool:
        """Restore one side of a structure-aware pixel transition."""
        ...


class LayerPixelOwnerRegistry:
    """Own the unique mapping from editable layer sources to pixel owners."""

    def __init__(self) -> None:
        """Initialize an empty ordered owner collection."""
        self._owners: list[LayerPixelMutationOwner] = []

    def register(self, owner: LayerPixelMutationOwner) -> None:
        """Register one source-domain owner exactly once."""
        if owner not in self._owners:
            self._owners.append(owner)

    def unregister(self, owner: LayerPixelMutationOwner) -> None:
        """Remove one source-domain owner by identity."""
        self._owners = [
            candidate for candidate in self._owners if candidate is not owner
        ]

    def owner_for(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
    ) -> LayerPixelMutationOwner | None:
        """Return the sole registered owner accepting ``layer``."""
        return next(
            (owner for owner in self._owners if owner.supports_layer(scene, layer)),
            None,
        )

    def content_bounds(
        self,
        scene: SceneDescriptor,
        layer: LayerDescriptor,
    ) -> RasterBounds | None:
        """Return source-owned meaningful bounds for one editable layer."""
        owner = self.owner_for(scene, layer)
        return None if owner is None else owner.content_bounds(layer)
