#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Generic selection-constrained pixel edit routing for scene layers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import numpy as np

from ..composition.edit_controller import CompositionEditController
from ..composition.edit_history import CompositionEditCommand
from ..selection import LayerCoverageProjector, PixelSelectionService
from .layer_selection import SceneLayerSelectionController
from .mutations import SceneMutationCoordinator
from .pixel_owners import LayerPixelOwnerRegistry
from .raster import RasterBounds
from .source_references import LayerSourceReference


@dataclass(frozen=True, slots=True)
class RasterPixelEdit:
    """Capture one source-local raster patch transition."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    source: LayerSourceReference
    bounds: RasterBounds
    before: np.ndarray
    after: np.ndarray

    def __post_init__(self) -> None:
        """Detach patch arrays retained for chronological history."""
        object.__setattr__(self, "before", np.array(self.before, copy=True, order="C"))
        object.__setattr__(self, "after", np.array(self.after, copy=True, order="C"))

    @property
    def scope_id(self) -> uuid.UUID:
        """Return the scene identity owning this edit."""
        return self.scene_id

    @property
    def retained_bytes(self) -> int:
        """Return patch bytes retained for undo and redo."""
        return int(self.before.nbytes + self.after.nbytes)

    @property
    def retained_resources(self) -> tuple[LayerSourceReference, ...]:
        """Retain the edited source while this command remains replayable."""
        return (self.source,)


class LayerPixelMutationCoordinator:
    """Authorize, project, record, and replay selection-constrained pixel edits."""

    def __init__(
        self,
        *,
        scene_mutations: SceneMutationCoordinator,
        layer_selection: SceneLayerSelectionController,
        pixel_selection: PixelSelectionService,
        owners: LayerPixelOwnerRegistry,
        edit_controller: CompositionEditController,
    ) -> None:
        """Bind scene state and install one history handler for raster patches."""
        self._scene_mutations = scene_mutations
        self._layer_selection = layer_selection
        self._pixel_selection = pixel_selection
        self._owners = owners
        self._edit_controller = edit_controller
        self._projector = LayerCoverageProjector()
        edit_controller.register_handler(
            RasterPixelEdit,
            undo=self._undo,
            redo=self._redo,
        )

    def clear_selected_pixels(self) -> bool:
        """Clear selected coverage from the selected editable layer."""
        selection = self._layer_selection.current
        if selection is None:
            return False
        resolved = self._scene_mutations.find_layer(
            lambda layer: (
                layer.scene_id == selection.scene_id
                and layer.layer_id == selection.layer_id
            )
        )
        if resolved is None:
            return False
        scene, layer = resolved
        if (
            not layer.interaction.pixel_editable
            or not layer.capabilities.raster_editable
        ):
            return False
        scene_coverage = self._pixel_selection.state(scene.scene_id).coverage
        if (
            scene_coverage is None
            or layer.transform is None
            or layer.raster_bounds is None
        ):
            return False
        local_coverage = self._projector.project_to_layer(
            scene_coverage,
            layer.transform,
            layer.raster_bounds,
        )
        if local_coverage is None or local_coverage.bounds is None:
            return False
        owner = self._owners.owner_for(scene, layer)
        if owner is None:
            return False
        before = owner.capture_patch(layer, local_coverage.bounds)
        if before is None or not owner.clear_coverage(layer, local_coverage):
            return False
        after = owner.capture_patch(layer, local_coverage.bounds)
        if after is None:
            owner.restore_patch(layer, local_coverage.bounds, before)
            return False
        self._edit_controller.record_applied(
            RasterPixelEdit(
                scene_id=scene.scene_id,
                layer_id=layer.layer_id,
                source=layer.source,
                bounds=local_coverage.bounds,
                before=before,
                after=after,
            )
        )
        return True

    def _undo(self, command: CompositionEditCommand) -> bool:
        """Restore the before-patch of a chronological raster edit."""
        return self._restore(command, use_after=False)

    def _redo(self, command: CompositionEditCommand) -> bool:
        """Restore the after-patch of a chronological raster edit."""
        return self._restore(command, use_after=True)

    def _restore(self, command: CompositionEditCommand, *, use_after: bool) -> bool:
        """Route one history patch back to its current source owner."""
        if not isinstance(command, RasterPixelEdit):
            return False
        resolved = self._scene_mutations.find_layer(
            lambda layer: (
                layer.scene_id == command.scene_id
                and layer.layer_id == command.layer_id
            )
        )
        if resolved is None:
            return False
        scene, layer = resolved
        owner = self._owners.owner_for(scene, layer)
        if owner is None:
            return False
        pixels = command.after if use_after else command.before
        return owner.restore_patch(layer, command.bounds, pixels)
