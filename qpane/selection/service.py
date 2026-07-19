#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Authoritative composition-scoped pixel-selection lifecycle."""

from __future__ import annotations

import uuid
from collections.abc import Callable

import numpy as np

from ..coverage import CoverageCombineMode, CoverageSnapshot
from ..scene.raster import RasterBounds, RasterExtentPolicy
from .compositor import compose_selection_coverage
from .history import PixelSelectionEdit
from .model import PixelSelectionState


class PixelSelectionService:
    """Own active coverage and revisions independently for each scene."""

    def __init__(
        self,
        changed: Callable[[PixelSelectionState], None] | None = None,
        record_edit: Callable[[PixelSelectionEdit], None] | None = None,
    ) -> None:
        """Initialize empty selection state with an optional observer."""
        self._coverage_by_scene: dict[uuid.UUID, CoverageSnapshot] = {}
        self._revision_by_scene: dict[uuid.UUID, int] = {}
        self._changed = changed
        self._record_edit = record_edit

    def state(self, scene_id: uuid.UUID) -> PixelSelectionState:
        """Return immutable selection state for ``scene_id``."""
        return PixelSelectionState(
            scene_id=scene_id,
            revision=self._revision_by_scene.get(scene_id, 0),
            coverage=self._coverage_by_scene.get(scene_id),
        )

    def commit(
        self,
        scene_id: uuid.UUID,
        incoming: CoverageSnapshot,
        mode: CoverageCombineMode = CoverageCombineMode.REPLACE,
    ) -> bool:
        """Combine incoming coverage into one scene's active selection."""
        previous = self._coverage_by_scene.get(scene_id)
        result = compose_selection_coverage(previous, incoming, mode)
        if _coverage_equal(previous, result):
            return False
        if result is None:
            self._coverage_by_scene.pop(scene_id, None)
        else:
            self._coverage_by_scene[scene_id] = result
        if self._record_edit is not None:
            self._record_edit(PixelSelectionEdit(scene_id, previous, result))
        self._publish(scene_id)
        return True

    def clear(self, scene_id: uuid.UUID) -> bool:
        """Clear one scene's active selection."""
        previous = self._coverage_by_scene.pop(scene_id, None)
        if previous is None:
            return False
        if self._record_edit is not None:
            self._record_edit(PixelSelectionEdit(scene_id, previous, None))
        self._publish(scene_id)
        return True

    def restore(self, scene_id: uuid.UUID, coverage: CoverageSnapshot | None) -> bool:
        """Restore history coverage without recording another command."""
        previous = self._coverage_by_scene.get(scene_id)
        if _coverage_equal(previous, coverage):
            return False
        if coverage is None:
            self._coverage_by_scene.pop(scene_id, None)
        else:
            self._coverage_by_scene[scene_id] = coverage
        self._publish(scene_id)
        return True

    def undo_edit(self, command: PixelSelectionEdit) -> bool:
        """Restore the selection captured before ``command``."""
        return self.restore(command.scene_id, command.before)

    def redo_edit(self, command: PixelSelectionEdit) -> bool:
        """Restore the selection captured after ``command``."""
        return self.restore(command.scene_id, command.after)

    def select_all(self, scene_id: uuid.UUID, bounds: RasterBounds) -> bool:
        """Replace active selection with full coverage inside ``bounds``."""
        return self.commit(
            scene_id,
            CoverageSnapshot(
                bounds=bounds,
                extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
                pixels=np.full((bounds.height, bounds.width), 255, dtype=np.uint8),
            ),
        )

    def invert(self, scene_id: uuid.UUID, bounds: RasterBounds) -> bool:
        """Invert active coverage within finite scene ``bounds``."""
        current = self._coverage_by_scene.get(scene_id)
        projected = np.zeros((bounds.height, bounds.width), dtype=np.uint8)
        if current is not None and current.bounds is not None:
            overlap = current.bounds.intersection(bounds)
            if overlap is not None:
                source_x = overlap.x - current.bounds.x
                source_y = overlap.y - current.bounds.y
                target_x = overlap.x - bounds.x
                target_y = overlap.y - bounds.y
                projected[
                    target_y : target_y + overlap.height,
                    target_x : target_x + overlap.width,
                ] = current.pixels[
                    source_y : source_y + overlap.height,
                    source_x : source_x + overlap.width,
                ]
        return self.commit(
            scene_id,
            CoverageSnapshot(
                bounds=bounds,
                extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
                pixels=np.subtract(255, projected, dtype=np.uint8),
            ),
        )

    def remove_scene(self, scene_id: uuid.UUID) -> bool:
        """Discard selection and revision state for a removed scene."""
        changed = self._coverage_by_scene.pop(scene_id, None) is not None
        self._revision_by_scene.pop(scene_id, None)
        return changed

    def clear_all(self) -> None:
        """Discard selections and revisions for every scene."""
        self._coverage_by_scene.clear()
        self._revision_by_scene.clear()

    def _publish(self, scene_id: uuid.UUID) -> None:
        """Advance revision and notify the configured observer."""
        self._revision_by_scene[scene_id] = self._revision_by_scene.get(scene_id, 0) + 1
        if self._changed is not None:
            self._changed(self.state(scene_id))


def _coverage_equal(
    left: CoverageSnapshot | None,
    right: CoverageSnapshot | None,
) -> bool:
    """Return whether optional snapshots contain identical coverage state."""
    if left is None or right is None:
        return left is right
    return (
        left.bounds == right.bounds
        and left.extent_policy is right.extent_policy
        and np.array_equal(left.pixels, right.pixels)
    )
