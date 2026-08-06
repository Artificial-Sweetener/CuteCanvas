#    CuteCanvas - High-performance layered image editor
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""Generic selection-constrained pixel edit routing for scene layers."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from qpane.sdk.scene import LayerSourceReference, RasterBounds

from ..composition.edit_controller import CompositionEditController
from ..selection import LayerCoverageProjector, PixelSelectionService
from .layer_selection import SceneLayerSelectionController
from .mutations import SceneMutationCoordinator
from .pixel_owners import LayerPixelOwnerRegistry


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


@dataclass(frozen=True, slots=True)
class LayerPixelContentChange:
    """Identify one durable layer-pixel mutation for host notification."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    source: LayerSourceReference


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
        changed: Callable[[LayerPixelContentChange], None],
    ) -> None:
        """Bind scene state and install one history handler for raster patches."""
        self._scene_mutations = scene_mutations
        self._layer_selection = layer_selection
        self._pixel_selection = pixel_selection
        self._owners = owners
        self._edit_controller = edit_controller
        self._changed = changed
        self._projector = LayerCoverageProjector()

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
        content_bounds = owner.content_bounds(layer)
        editable_coverage = (
            None
            if content_bounds is None
            else local_coverage.clipped_to(content_bounds)
        )
        if editable_coverage is None or editable_coverage.bounds is None:
            return False
        edit_bounds = editable_coverage.bounds
        before = owner.capture_patch(layer, edit_bounds)
        if before is None or not owner.clear_coverage(layer, editable_coverage):
            return False
        after = owner.capture_patch(layer, edit_bounds)
        if after is None:
            owner.restore_patch(layer, edit_bounds, before)
            return False
        owner.finalize_patch_edit(layer)
        edit = RasterPixelEdit(
            scene_id=scene.scene_id,
            layer_id=layer.layer_id,
            source=layer.source,
            bounds=edit_bounds,
            before=before,
            after=after,
        )
        self._edit_controller.record_applied(edit)
        self._changed(
            LayerPixelContentChange(edit.scene_id, edit.layer_id, edit.source)
        )
        return True
