#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Policy-aware resolution of selected editable raster content."""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPointF

from ..coverage import CoverageCombineMode, CoverageSnapshot
from ..scene.layer_selection import SceneLayerSelection, SceneLayerSelectionController
from ..scene.model import LayerDescriptor, SceneDescriptor
from ..scene.mutations import SceneMutationCoordinator
from ..scene.pixel_owners import LayerPixelMutationOwner, LayerPixelOwnerRegistry
from ..scene.raster import RasterExtentPolicy
from ..selection import (
    LayerCoverageProjector,
    PixelSelectionService,
    compose_selection_coverage,
)
from .selection_projection import LayerSelectionProjectionCache


@dataclass(frozen=True, slots=True)
class SelectedPixelMoveTarget:
    """Retain one resolved layer, selection, and authoritative pixel owner."""

    scene: SceneDescriptor
    layer: LayerDescriptor
    selection: CoverageSnapshot
    scene_coverage: CoverageSnapshot
    local_coverage: CoverageSnapshot
    extent_policy: RasterExtentPolicy
    owner: LayerPixelMutationOwner


class SelectedPixelMoveTargetResolver:
    """Resolve movement eligibility without owning editor or source state."""

    def __init__(
        self,
        *,
        active_scene: Callable[[], SceneDescriptor | None],
        scene_mutations: SceneMutationCoordinator,
        layer_selection: SceneLayerSelectionController,
        pixel_selection: PixelSelectionService,
        pixel_owners: LayerPixelOwnerRegistry,
        selection_projections: LayerSelectionProjectionCache,
    ) -> None:
        """Bind authoritative selection, scene, and source-owner collaborators."""
        self._active_scene = active_scene
        self._scene_mutations = scene_mutations
        self._layer_selection = layer_selection
        self._pixel_selection = pixel_selection
        self._pixel_owners = pixel_owners
        self._selection_projections = selection_projections
        self._projector = LayerCoverageProjector()

    @property
    def selected_layer(self) -> SceneLayerSelection | None:
        """Return authoritative generic layer selection."""
        return self._layer_selection.current

    def has_selection(self) -> bool:
        """Return whether the active scene owns nonempty pixel selection coverage."""
        scene = self._active_scene()
        return bool(
            scene is not None
            and self._pixel_selection.state(scene.scene_id).coverage is not None
        )

    def resolve_at(self, scene_point: QPointF) -> SelectedPixelMoveTarget | None:
        """Resolve selected editable content only when ``scene_point`` is covered."""
        target = self.resolve_selected()
        if target is None or not coverage_contains(target.scene_coverage, scene_point):
            return None
        return target

    def resolve_selected(self) -> SelectedPixelMoveTarget | None:
        """Resolve active selection coverage through its selected source owner."""
        scene = self._active_scene()
        selected = self._layer_selection.current
        if scene is None or selected is None or selected.scene_id != scene.scene_id:
            return None
        selection_state = self._pixel_selection.state(scene.scene_id)
        selection = selection_state.coverage
        if selection is None:
            return None
        resolved = self._scene_mutations.find_layer(
            lambda layer: (
                layer.scene_id == selected.scene_id
                and layer.layer_id == selected.layer_id
            )
        )
        if resolved is None:
            return None
        resolved_scene, layer = resolved
        if not self._layer_is_editable(layer):
            return None
        local_selection = self._selection_projections.resolve(
            scene_id=scene.scene_id,
            layer_id=layer.layer_id,
            selection_revision=selection_state.revision,
            transform=layer.transform,
        )
        if local_selection is None:
            local_selection = self._projector.project_to_layer(
                selection,
                layer.transform,
                layer.raster_bounds,
            )
        if (
            local_selection is None
            or local_selection.bounds is None
            or not local_selection.pixels.any()
        ):
            return None
        owner = self._pixel_owners.owner_for(resolved_scene, layer)
        if owner is None:
            return None
        content = owner.content_coverage(layer, local_selection.bounds)
        if content is None:
            return None
        local = compose_selection_coverage(
            local_selection,
            content,
            CoverageCombineMode.INTERSECT,
        )
        if local is None:
            return None
        scene_coverage = self._projector.project(local, layer.transform)
        if scene_coverage is None:
            return None
        extent_policy = owner.extent_policy(layer)
        if extent_policy is None:
            return None
        return SelectedPixelMoveTarget(
            resolved_scene,
            layer,
            selection,
            scene_coverage,
            local,
            extent_policy,
            owner,
        )

    def resolve_layer(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> tuple[SceneDescriptor, LayerDescriptor, LayerPixelMutationOwner] | None:
        """Resolve a continuing session through current policy and ownership."""
        resolved = self._scene_mutations.find_layer(
            lambda layer: layer.scene_id == scene_id and layer.layer_id == layer_id
        )
        if resolved is None:
            return None
        scene, layer = resolved
        if not self._layer_is_editable(layer):
            return None
        owner = self._pixel_owners.owner_for(scene, layer)
        return None if owner is None else (scene, layer, owner)

    @staticmethod
    def _layer_is_editable(layer: LayerDescriptor) -> bool:
        """Return whether interaction, capability, and geometry permit editing."""
        transform = layer.transform
        return bool(
            layer.interaction.pixel_editable
            and layer.capabilities.raster_editable
            and transform is not None
            and layer.raster_bounds is not None
            and transform.is_invertible
        )


def coverage_contains(coverage: CoverageSnapshot, point: QPointF) -> bool:
    """Return whether a scene point lies inside nonzero selection coverage."""
    bounds = coverage.bounds
    if bounds is None:
        return False
    x = math.floor(point.x())
    y = math.floor(point.y())
    if x < bounds.x or y < bounds.y or x >= bounds.right or y >= bounds.bottom:
        return False
    return bool(coverage.pixels[y - bounds.y, x - bounds.x])
