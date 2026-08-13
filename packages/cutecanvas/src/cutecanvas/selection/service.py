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
"""Authoritative composition-scoped pixel-selection lifecycle."""

from __future__ import annotations

import uuid
from collections.abc import Callable

import numpy as np

from cutecanvas.coverage import (
    CoverageCombineMode,
    CoverageDocument,
    CoverageDocumentEvaluator,
    CoverageItem,
    CoverageSnapshot,
    RasterCoverageItem,
)
from cutecanvas.types import RasterExtentPolicy
from qpane.sdk.scene import RasterBounds

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
        self._documents_by_scene: dict[uuid.UUID, CoverageDocument] = {}
        self._coverage_by_scene: dict[uuid.UUID, CoverageSnapshot] = {}
        self._revision_by_scene: dict[uuid.UUID, int] = {}
        self._changed = changed
        self._record_edit = record_edit
        self._evaluator = CoverageDocumentEvaluator()

    def state(self, scene_id: uuid.UUID) -> PixelSelectionState:
        """Return immutable selection state for ``scene_id``."""
        return PixelSelectionState(
            scene_id=scene_id,
            revision=self._revision_by_scene.get(scene_id, 0),
            coverage=self._coverage_by_scene.get(scene_id),
        )

    def document(self, scene_id: uuid.UUID) -> CoverageDocument | None:
        """Return the immutable authored selection document for ``scene_id``."""
        return self._documents_by_scene.get(scene_id)

    def commit(
        self,
        scene_id: uuid.UUID,
        incoming: CoverageSnapshot,
        mode: CoverageCombineMode = CoverageCombineMode.REPLACE,
    ) -> bool:
        """Combine incoming coverage into one scene's active selection."""
        item = RasterCoverageItem(uuid.uuid4(), incoming, mode)
        return self.commit_item(scene_id, item)

    def commit_item(self, scene_id: uuid.UUID, item: CoverageItem) -> bool:
        """Commit one retained coverage item to a scene selection."""
        previous = self._documents_by_scene.get(scene_id)
        base = CoverageDocument() if previous is None else previous
        operation = CoverageCombineMode.ADD if previous is None else item.combine_mode
        after = (
            base.replaced_by(_with_combine_mode(item, CoverageCombineMode.ADD))
            if operation is CoverageCombineMode.REPLACE
            else base.add(_with_combine_mode(item, operation))
        )
        if self._evaluator.content_bounds(after) is None:
            normalized: CoverageDocument | None = None
        else:
            normalized = after
        previous_coverage = self._coverage_by_scene.get(scene_id)
        normalized_coverage = (
            None if normalized is None else self._evaluator.rasterize(normalized)
        )
        if _coverage_equal(previous_coverage, normalized_coverage):
            return False
        self._set_document(
            scene_id,
            normalized,
            coverage=normalized_coverage,
        )
        if self._record_edit is not None:
            self._record_edit(PixelSelectionEdit(scene_id, previous, normalized))
        self._publish(scene_id)
        return True

    def clear(self, scene_id: uuid.UUID) -> bool:
        """Clear one scene's active selection."""
        previous = self._documents_by_scene.pop(scene_id, None)
        if previous is None:
            return False
        self._coverage_by_scene.pop(scene_id, None)
        if self._record_edit is not None:
            self._record_edit(PixelSelectionEdit(scene_id, previous, None))
        self._publish(scene_id)
        return True

    def restore_document(
        self,
        scene_id: uuid.UUID,
        document: CoverageDocument | None,
        *,
        coverage: CoverageSnapshot | None = None,
    ) -> bool:
        """Restore authored state with an optional already-evaluated projection."""
        previous = self._documents_by_scene.get(scene_id)
        if previous == document:
            return False
        self._set_document(scene_id, document, coverage=coverage)
        self._publish(scene_id)
        return True

    def replace_with_raster(
        self,
        scene_id: uuid.UUID,
        coverage: CoverageSnapshot | None,
    ) -> bool:
        """Replace live selection state with one explicit raster projection."""
        document = (
            None
            if coverage is None
            else CoverageDocument().add(RasterCoverageItem(uuid.uuid4(), coverage))
        )
        return self.restore_document(scene_id, document)

    def replace_coverage(
        self,
        scene_id: uuid.UUID,
        coverage: CoverageSnapshot | None,
        *,
        expected_revision: int,
    ) -> bool:
        """Commit one revision-guarded evaluated replacement with history."""
        if self._revision_by_scene.get(scene_id, 0) != expected_revision:
            return False
        previous = self._documents_by_scene.get(scene_id)
        previous_coverage = self._coverage_by_scene.get(scene_id)
        if _coverage_equal(previous_coverage, coverage):
            return False
        replacement = (
            None
            if coverage is None
            else CoverageDocument().add(RasterCoverageItem(uuid.uuid4(), coverage))
        )
        self._set_document(scene_id, replacement, coverage=coverage)
        if self._record_edit is not None:
            self._record_edit(PixelSelectionEdit(scene_id, previous, replacement))
        self._publish(scene_id)
        return True

    def preview_document(
        self,
        scene_id: uuid.UUID,
        document: CoverageDocument | None,
        *,
        coverage: CoverageSnapshot | None = None,
    ) -> bool:
        """Publish one unresolved authored preview without recording history."""
        return self.restore_document(scene_id, document, coverage=coverage)

    def preview_coverage(
        self,
        scene_id: uuid.UUID,
        coverage: CoverageSnapshot | None,
        *,
        expected_revision: int,
    ) -> bool:
        """Replace one revision-guarded preview without recording history."""

        if self._revision_by_scene.get(scene_id, 0) != expected_revision:
            return False
        replacement = (
            None
            if coverage is None
            else CoverageDocument().add(RasterCoverageItem(uuid.uuid4(), coverage))
        )
        return self.preview_document(scene_id, replacement, coverage=coverage)

    def record_preview(
        self,
        scene_id: uuid.UUID,
        before: CoverageDocument | None,
    ) -> bool:
        """Record a live-preview transition without republishing or replacing it."""
        after = self._documents_by_scene.get(scene_id)
        if before == after:
            return False
        if self._record_edit is not None:
            self._record_edit(PixelSelectionEdit(scene_id, before, after))
        return True

    def undo_edit(self, command: PixelSelectionEdit) -> bool:
        """Restore the selection captured before ``command``."""
        return self.restore_document(command.scene_id, command.before)

    def redo_edit(self, command: PixelSelectionEdit) -> bool:
        """Restore the selection captured after ``command``."""
        return self.restore_document(command.scene_id, command.after)

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
        current = self.state(scene_id).coverage
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
        changed = self._documents_by_scene.pop(scene_id, None) is not None
        self._coverage_by_scene.pop(scene_id, None)
        self._revision_by_scene.pop(scene_id, None)
        return changed

    def clear_all(self) -> None:
        """Discard selections and revisions for every scene."""
        self._documents_by_scene.clear()
        self._coverage_by_scene.clear()
        self._revision_by_scene.clear()

    def _publish(self, scene_id: uuid.UUID) -> None:
        """Advance revision and notify the configured observer."""
        self._revision_by_scene[scene_id] = self._revision_by_scene.get(scene_id, 0) + 1
        if self._changed is not None:
            self._changed(self.state(scene_id))

    def _set_document(
        self,
        scene_id: uuid.UUID,
        document: CoverageDocument | None,
        *,
        coverage: CoverageSnapshot | None = None,
    ) -> None:
        """Install one immutable document and its evaluated presentation."""
        if document is None or not document.items:
            self._documents_by_scene.pop(scene_id, None)
            self._coverage_by_scene.pop(scene_id, None)
        else:
            self._documents_by_scene[scene_id] = document
            self._coverage_by_scene[scene_id] = (
                self._evaluator.rasterize(document) if coverage is None else coverage
            )


def _with_combine_mode(
    item: CoverageItem,
    mode: CoverageCombineMode,
) -> CoverageItem:
    """Return one authored item with replacement algebra normalized."""
    from dataclasses import replace

    return replace(item, combine_mode=mode)


def _coverage_equal(
    left: CoverageSnapshot | None,
    right: CoverageSnapshot | None,
) -> bool:
    """Return whether optional evaluated snapshots are pixel-identical."""
    if left is None or right is None:
        return left is right
    return (
        left.bounds == right.bounds
        and left.extent_policy is right.extent_policy
        and np.array_equal(left.pixels, right.pixels)
    )
