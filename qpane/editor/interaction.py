#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Source-neutral coordination of layer and pixel-selection interactions."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from math import ceil, floor

from ..coverage import CoverageCombineMode, CoverageSnapshot
from ..scene.layer_selection import SceneLayerSelection, SceneLayerSelectionController
from ..scene.model import SceneDescriptor
from ..scene.mutations import SceneMutationCoordinator
from ..scene.pixel_edits import LayerPixelMutationCoordinator
from ..scene.raster import RasterBounds
from ..scene.registry import LayerSourceResolverRegistry
from ..scene.sources import MaskLayerSource
from ..selection import (
    LayerCoverageProjector,
    PixelSelectionService,
    PixelSelectionState,
)
from .selection_projection import LayerSelectionProjectionCache


class EditorInteractionCoordinator:
    """Own cross-domain editor interaction policy without owning domain state."""

    def __init__(
        self,
        *,
        active_scene: Callable[[], SceneDescriptor | None],
        scene_mutations: SceneMutationCoordinator,
        layer_selection: SceneLayerSelectionController,
        pixel_selection: PixelSelectionService,
        pixel_mutations: LayerPixelMutationCoordinator,
        source_resolvers: LayerSourceResolverRegistry,
        selection_projections: LayerSelectionProjectionCache,
    ) -> None:
        """Bind authoritative scene, selection, mutation, and source owners."""
        self._active_scene = active_scene
        self._scene_mutations = scene_mutations
        self._layer_selection = layer_selection
        self._pixel_selection = pixel_selection
        self._pixel_mutations = pixel_mutations
        self._source_resolvers = source_resolvers
        self._selection_projections = selection_projections
        self._coverage_projector = LayerCoverageProjector()

    @property
    def selected_layer(self) -> SceneLayerSelection | None:
        """Return stable generic layer selection."""
        return self._layer_selection.current

    def select_layer(self, scene_id: uuid.UUID, layer_id: uuid.UUID) -> bool:
        """Select one policy-enabled layer in the active scene."""
        resolved = self._scene_mutations.find_layer(
            lambda layer: layer.scene_id == scene_id and layer.layer_id == layer_id
        )
        if resolved is None or not resolved[1].interaction.selectable:
            return False
        return self._layer_selection.select(scene_id, layer_id)

    def clear_selected_layer(self) -> bool:
        """Clear layer selection without changing pixel selection."""
        return self._layer_selection.clear()

    def pixel_selection_state(self, scene_id: uuid.UUID) -> PixelSelectionState:
        """Return immutable pixel-selection state for one scene."""
        return self._pixel_selection.state(scene_id)

    def commit_pixel_selection(
        self,
        scene_id: uuid.UUID,
        coverage: CoverageSnapshot,
        mode: CoverageCombineMode,
    ) -> bool:
        """Combine coverage into one scene's pixel selection."""
        return self._pixel_selection.commit(scene_id, coverage, mode)

    def commit_active_pixel_selection(
        self,
        coverage: CoverageSnapshot,
        mode: CoverageCombineMode,
    ) -> bool:
        """Combine tool-produced coverage into the active scene selection."""
        scene = self._active_scene()
        return bool(
            scene is not None
            and self._pixel_selection.commit(scene.scene_id, coverage, mode)
        )

    def clear_pixel_selection(self, scene_id: uuid.UUID) -> bool:
        """Clear one scene's pixel selection."""
        return self._pixel_selection.clear(scene_id)

    def select_all_pixels(self, scene_id: uuid.UUID) -> bool:
        """Select the active scene's finite canvas bounds."""
        bounds = self._active_scene_bounds(scene_id)
        return bool(
            bounds is not None and self._pixel_selection.select_all(scene_id, bounds)
        )

    def invert_pixel_selection(self, scene_id: uuid.UUID) -> bool:
        """Invert pixel selection inside the active scene's finite canvas."""
        bounds = self._active_scene_bounds(scene_id)
        return bool(
            bounds is not None and self._pixel_selection.invert(scene_id, bounds)
        )

    def select_layer_coverage(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        mode: CoverageCombineMode,
    ) -> bool:
        """Project a coverage-producing layer into composition selection."""
        resolved = self._scene_mutations.find_layer(
            lambda layer: layer.scene_id == scene_id and layer.layer_id == layer_id
        )
        if resolved is None:
            return False
        layer = resolved[1]
        coverage = self._source_resolvers.coverage_snapshot(layer.source)
        if coverage is None or layer.transform is None:
            return False
        projected = self._coverage_projector.project(coverage, layer.transform)
        if projected is None or not self._pixel_selection.commit(
            scene_id,
            projected,
            mode,
        ):
            return False
        if mode is CoverageCombineMode.REPLACE:
            state = self._pixel_selection.state(scene_id)
            self._selection_projections.remember(
                scene_id=scene_id,
                layer_id=layer_id,
                selection_revision=state.revision,
                transform=layer.transform,
                coverage=coverage,
            )
        return True

    def delete_selected_pixels(self) -> bool:
        """Route selection-constrained deletion to the selected source owner."""
        return self._pixel_mutations.clear_selected_pixels()

    def mask_stroke_constraint(
        self,
        mask_id: uuid.UUID,
    ) -> CoverageSnapshot | None:
        """Project active selection into one unbounded mask's local coordinates."""
        scene = self._active_scene()
        if scene is None:
            return None
        selection = self._pixel_selection.state(scene.scene_id).coverage
        if selection is None:
            return None
        layer = next(
            (
                candidate
                for candidate in scene.layers
                if isinstance(candidate.source, MaskLayerSource)
                and candidate.source.mask_id == mask_id
            ),
            None,
        )
        if layer is None or layer.transform is None:
            return None
        return self._coverage_projector.project_to_layer(selection, layer.transform)

    def _active_scene_bounds(self, scene_id: uuid.UUID) -> RasterBounds | None:
        """Return integer canvas bounds when ``scene_id`` is currently active."""
        scene = self._active_scene()
        if scene is None or scene.scene_id != scene_id:
            return None
        left = floor(scene.bounds.x)
        top = floor(scene.bounds.y)
        right = ceil(scene.bounds.x + scene.bounds.width)
        bottom = ceil(scene.bounds.y + scene.bounds.height)
        if right <= left or bottom <= top:
            return None
        return RasterBounds(left, top, right - left, bottom - top)
