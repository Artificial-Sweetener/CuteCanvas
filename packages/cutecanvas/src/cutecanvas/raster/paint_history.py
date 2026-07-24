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
"""Bounded tile-patch history shared by every editable-raster brush operation."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from qpane.sdk.scene import RasterBounds

from ..composition.edit_controller import CompositionEditController
from ..resources import ProjectResourceReference
from .assets import EditableRasterAssetStore


@dataclass(frozen=True, slots=True)
class RasterPaintPatch:
    """Retain one bounded changed tile for exact paint history."""

    bounds: RasterBounds
    before: np.ndarray
    after: np.ndarray

    def __post_init__(self) -> None:
        """Detach and validate premultiplied tile pixels."""
        expected = (self.bounds.height, self.bounds.width, 4)
        before = np.array(self.before, copy=True, order="C")
        after = np.array(self.after, copy=True, order="C")
        if (
            before.dtype != np.uint8
            or after.dtype != np.uint8
            or before.shape != expected
            or after.shape != expected
        ):
            raise ValueError("paint patch pixels must match BGRA tile bounds")
        before.flags.writeable = False
        after.flags.writeable = False
        object.__setattr__(self, "before", before)
        object.__setattr__(self, "after", after)

    @property
    def retained_bytes(self) -> int:
        """Return exact history bytes retained by this tile."""
        return int(self.before.nbytes + self.after.nbytes)


@dataclass(frozen=True, slots=True)
class RasterPaintEdit:
    """Capture one complete paint stroke as bounded tile transitions."""

    scene_id: uuid.UUID
    layer_id: uuid.UUID
    raster_id: uuid.UUID
    before_bounds: RasterBounds
    after_bounds: RasterBounds
    patches: tuple[RasterPaintPatch, ...]

    @property
    def scope_id(self) -> uuid.UUID:
        """Return the scene history scope owning this stroke."""
        return self.scene_id

    @property
    def retained_bytes(self) -> int:
        """Return exact retained patch bytes plus compact metadata."""
        return 256 + sum(patch.retained_bytes for patch in self.patches)

    @property
    def retained_resources(self) -> tuple[ProjectResourceReference, ...]:
        """Retain the edited raster while this command remains in history."""
        return (ProjectResourceReference(self.raster_id),)


class RasterPaintHistory:
    """Record and replay all editable-raster brush operations through one owner."""

    def __init__(
        self,
        *,
        assets: EditableRasterAssetStore,
        edits: CompositionEditController,
        changed: Callable[[uuid.UUID, RasterBounds], None],
        structure_changed: Callable[[uuid.UUID], None],
    ) -> None:
        """Bind raster resources, document history, and presentation damage."""
        self._assets = assets
        self._edits = edits
        self._changed = changed
        self._structure_changed = structure_changed
        edits.register_handler(
            RasterPaintEdit,
            undo=self._undo,
            redo=self._redo,
        )

    def record_applied(self, edit: RasterPaintEdit) -> None:
        """Record one already-applied atomic raster transition."""
        self._edits.record_applied(edit)

    def _undo(self, command: object) -> bool:
        """Restore the exact raster state preceding one brush stroke."""
        return self._restore_edit(command, use_after=False)

    def _redo(self, command: object) -> bool:
        """Restore the exact raster state following one brush stroke."""
        return self._restore_edit(command, use_after=True)

    def _restore_edit(self, command: object, *, use_after: bool) -> bool:
        """Replay one paint command directly through its retained source."""
        if not isinstance(command, RasterPaintEdit):
            return False
        asset = self._assets.get(command.raster_id)
        if asset is None:
            return False
        surface = asset.surface
        target_bounds = command.after_bounds if use_after else command.before_bounds
        structure_changed = surface.set_bounds(target_bounds)
        for patch in command.patches:
            overlap = target_bounds.intersection(patch.bounds)
            if overlap is None:
                continue
            pixels = patch.after if use_after else patch.before
            source_x = overlap.x - patch.bounds.x
            source_y = overlap.y - patch.bounds.y
            surface.restore_patch(
                overlap,
                pixels[
                    source_y : source_y + overlap.height,
                    source_x : source_x + overlap.width,
                ],
            )
            self._changed(command.raster_id, overlap)
        if structure_changed:
            self._structure_changed(command.raster_id)
        return True
