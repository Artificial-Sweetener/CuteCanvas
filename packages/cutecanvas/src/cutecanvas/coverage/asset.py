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
"""Hybrid coverage asset owning raster paint and retained authored items."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage
from qpane.sdk.raster import numpy_to_qimage_grayscale8
from qpane.sdk.scene import RasterBounds

from cutecanvas.types import RasterExtentPolicy

from ..raster.sparse_grid import SparseRasterSnapshot
from .content_bounds import occupied_coverage_bounds
from .document import CoverageDocument, CoverageItem, VectorCoverageItem
from .evaluation import CoverageDocumentEvaluator
from .operations import CoverageCombineMode, combine_coverage
from .raster_structure import CoverageRasterStructureState
from .state_bounds import coverage_state_content_bounds
from .surface import CoverageSnapshot, CoverageStateSnapshot, CoverageSurface

_EVALUATION_TILE_SIZE = 512


@dataclass(frozen=True, slots=True)
class CoverageAssetSnapshot:
    """Persist sparse raster storage and retained authorship as one asset."""

    raster: SparseRasterSnapshot
    retained: CoverageDocument
    authored_bounds: RasterBounds | None = None

    def __post_init__(self) -> None:
        """Validate the two authoritative coverage components."""
        if not isinstance(self.raster, SparseRasterSnapshot):
            raise TypeError("coverage asset raster must be a sparse snapshot")
        if not isinstance(self.retained, CoverageDocument):
            raise TypeError("coverage asset retained value must be a document")
        if self.authored_bounds is not None and not isinstance(
            self.authored_bounds, RasterBounds
        ):
            raise TypeError("coverage asset authored bounds must be raster bounds")


class CoverageAsset:
    """Own one mask/selection-compatible hybrid coverage resource."""

    def __init__(
        self,
        asset_id: uuid.UUID,
        raster: CoverageSurface,
        *,
        retained: CoverageDocument | None = None,
        authored_bounds: RasterBounds | None = None,
        evaluator: CoverageDocumentEvaluator | None = None,
    ) -> None:
        """Bind sparse raster paint and immutable retained authorship."""
        self.asset_id = asset_id
        self.raster = raster
        self.retained = retained or CoverageDocument(document_id=asset_id)
        self._authored_bounds = (
            raster.bounds if authored_bounds is None else authored_bounds
        )
        self._evaluator = evaluator or CoverageDocumentEvaluator(
            tile_size=_EVALUATION_TILE_SIZE
        )
        self._bounds_revision: tuple[int, int] | None = None
        self._content_bounds: RasterBounds | None = None
        self._manipulation_bounds_revision: tuple[int, int] | None = None
        self._manipulation_bounds: QRectF | None = None
        self._source_bounds_revision: tuple[int, int] | None = None
        self._source_bounds: RasterBounds | None = None

    @property
    def revision(self) -> tuple[int, int]:
        """Return raster and retained revisions as one cache identity."""
        return self.raster.generation, self.retained.revision

    @property
    def has_retained_items(self) -> bool:
        """Return whether semantic or procedural authorship remains editable."""
        return bool(self.retained.items)

    def append(self, item: CoverageItem) -> bool:
        """Commit one retained coverage contribution."""
        previous_source = self.source_bounds()
        previous_manipulation = self.manipulation_bounds()
        self.retained = self.retained.add(item)
        self._invalidate_bounds()
        self._retain_incremental_additive_bounds(
            item,
            previous_source=previous_source,
            previous_manipulation=previous_manipulation,
        )
        return True

    def restore_retained(self, document: CoverageDocument) -> bool:
        """Restore one immutable retained revision for history replay."""
        if document.document_id != self.asset_id:
            raise ValueError("coverage document identity must match its asset")
        if document == self.retained:
            return False
        previous = self.retained
        appended_item = (
            document.items[-1]
            if len(document.items) == len(previous.items) + 1
            and document.items[:-1] == previous.items
            else None
        )
        previous_source = self.source_bounds() if appended_item is not None else None
        previous_manipulation = (
            self.manipulation_bounds() if appended_item is not None else None
        )
        self.retained = document
        self._invalidate_bounds()
        if appended_item is not None:
            self._retain_incremental_additive_bounds(
                appended_item,
                previous_source=previous_source,
                previous_manipulation=previous_manipulation,
            )
        return True

    def snapshot(self, bounds: RasterBounds | None = None) -> CoverageSnapshot:
        """Evaluate raster and retained items in explicit or content-tight bounds."""
        target = bounds or self.source_bounds()
        if target is None:
            return _empty_snapshot(self.raster.extent_policy)
        pixels = self.raster.capture_region(target)
        for item in self.retained.items:
            contribution = self._evaluator.evaluate_item(item, target)
            pixels = combine_coverage(pixels, contribution, item.combine_mode)
        return CoverageSnapshot._adopt_detached(
            target,
            self.raster.extent_policy,
            np.ascontiguousarray(pixels),
        )

    def state_snapshot(self) -> CoverageAssetSnapshot:
        """Return the complete durable hybrid asset state without rasterization."""
        return CoverageAssetSnapshot(
            self.raster.sparse_snapshot(),
            self.retained,
            self._authored_bounds,
        )

    @classmethod
    def from_snapshot(
        cls,
        asset_id: uuid.UUID,
        snapshot: CoverageAssetSnapshot,
    ) -> CoverageAsset:
        """Restore one complete hybrid asset from detached durable state."""
        if snapshot.retained.document_id != asset_id:
            raise ValueError("coverage document identity must match its asset")
        return cls(
            asset_id,
            CoverageSurface.from_sparse_snapshot(snapshot.raster),
            retained=snapshot.retained,
            authored_bounds=(
                snapshot.raster.bounds
                if snapshot.authored_bounds is None
                else snapshot.authored_bounds
            ),
        )

    @property
    def authored_bounds(self) -> RasterBounds | None:
        """Return the stable finite extent established when the asset was authored."""
        return self._authored_bounds

    def set_authored_bounds(self, bounds: RasterBounds | None) -> bool:
        """Replace explicit presentation extent without exposing raster allocation."""
        if bounds == self._authored_bounds:
            return False
        self._authored_bounds = bounds
        self._invalidate_bounds()
        return True

    def raster_structure_state(self) -> CoverageRasterStructureState:
        """Capture storage and explicit authored extent as one structural state."""
        return CoverageRasterStructureState(
            self.raster.state_snapshot(),
            self._authored_bounds,
        )

    def restore_raster_structure(
        self,
        state: CoverageRasterStructureState,
    ) -> None:
        """Restore storage and authored extent atomically for history replay."""
        self.raster.replace_with_state_snapshot(state.raster)
        self._authored_bounds = state.authored_bounds
        self._invalidate_bounds()

    def compact_raster_storage(self) -> bool:
        """Shrink expandable raster allocation without changing authored extent."""
        changed = self.raster.compact_storage()
        if changed:
            self._invalidate_bounds()
        return changed

    def content_bounds(self) -> RasterBounds | None:
        """Return exact nonzero bounds independent of raster storage allocation."""
        revision = self.revision
        if revision == self._bounds_revision:
            return self._content_bounds
        if not self.retained.items:
            self._bounds_revision = revision
            self._content_bounds = self.raster.content_bounds()
            return self._content_bounds
        candidate = self.candidate_bounds()
        occupied: list[RasterBounds] = []
        if candidate is not None:
            for tile in _tiles_covering(candidate, _EVALUATION_TILE_SIZE):
                occupied_bounds = occupied_coverage_bounds(self.snapshot(tile))
                if occupied_bounds is not None:
                    occupied.append(occupied_bounds)
        self._bounds_revision = revision
        self._content_bounds = _union_bounds(occupied)
        return self._content_bounds

    def candidate_bounds(self) -> RasterBounds | None:
        """Return conservative bounds for rendering and exact-bound discovery."""
        current = self.raster.content_bounds()
        for item in self.retained.items:
            item_bounds = self._evaluator.candidate_bounds(
                CoverageDocument(items=(item,))
            )
            if item.combine_mode is CoverageCombineMode.REPLACE:
                current = item_bounds
            elif item.combine_mode is CoverageCombineMode.INTERSECT:
                current = (
                    None
                    if current is None or item_bounds is None
                    else current.intersection(item_bounds)
                )
            elif (
                item.combine_mode is CoverageCombineMode.ADD and item_bounds is not None
            ):
                current = (
                    item_bounds if current is None else current.united(item_bounds)
                )
        return current

    def manipulation_bounds(self) -> QRectF | None:
        """Return source-local bounds matching continuously rendered coverage."""
        revision = self.revision
        if revision == self._manipulation_bounds_revision:
            bounds = self._manipulation_bounds
            return None if bounds is None else QRectF(bounds)
        continuous, bounds = _continuous_manipulation_bounds(
            self.raster.content_bounds(),
            self.retained,
            self._evaluator,
        )
        if not continuous:
            content = self.content_bounds()
            bounds = None if content is None else _rectf(content)
        self._manipulation_bounds_revision = revision
        self._manipulation_bounds = None if bounds is None else QRectF(bounds)
        return None if bounds is None else QRectF(bounds)

    def source_bounds(self) -> RasterBounds | None:
        """Return the presentation extent spanning authored and visible coverage."""
        revision = self.revision
        if revision == self._source_bounds_revision:
            return self._source_bounds
        result = self._source_bounds_for_content(
            self.raster.content_bounds(),
            self._authored_bounds,
        )
        self._source_bounds_revision = revision
        self._source_bounds = result
        return result

    def source_bounds_for_raster_state(
        self,
        state: CoverageStateSnapshot,
    ) -> RasterBounds | None:
        """Return presentation bounds for one alternate detached raster state."""
        return self._source_bounds_for_content(
            coverage_state_content_bounds(state),
            self._authored_bounds,
        )

    def source_bounds_for_structure_state(
        self,
        state: CoverageRasterStructureState,
    ) -> RasterBounds | None:
        """Return presentation bounds for one complete alternate structure."""
        return self._source_bounds_for_content(
            coverage_state_content_bounds(state.raster),
            state.authored_bounds,
        )

    def _source_bounds_for_content(
        self,
        raster_content: RasterBounds | None,
        authored_bounds: RasterBounds | None,
    ) -> RasterBounds | None:
        """Combine stable authorship with visible raster and retained coverage."""
        current = authored_bounds
        if raster_content is not None:
            current = (
                raster_content if current is None else current.united(raster_content)
            )
        retained = self._evaluator.candidate_bounds(self.retained)
        result = (
            current
            if retained is None
            else retained if current is None else current.united(retained)
        )
        return result

    def coverage_value(self, x: int, y: int) -> int:
        """Return evaluated coverage at one asset-local coordinate."""
        return int(self.snapshot(RasterBounds(int(x), int(y), 1, 1)).pixels[0, 0])

    def snapshot_qimage(self) -> QImage:
        """Return the evaluated hybrid coverage as detached grayscale pixels."""
        snapshot = self.snapshot()
        if snapshot.bounds is None:
            return QImage()
        return numpy_to_qimage_grayscale8(snapshot.pixels)

    def snapshot_array(self) -> np.ndarray:
        """Return detached evaluated coverage pixels."""
        return np.array(self.snapshot().pixels, copy=True, order="C")

    def replace_raster_qimage(self, image: QImage) -> None:
        """Replace the raster item while preserving retained authorship."""
        self.raster.replace_with_qimage(image)

    def rasterize(self) -> bool:
        """Flatten retained items explicitly into sparse raster authority."""
        if not self.retained.items:
            return False
        snapshot = self.snapshot()
        self.raster = CoverageSurface(
            snapshot.pixels,
            bounds=snapshot.bounds,
            extent_policy=self.raster.extent_policy,
        )
        self.retained = self.retained.clear()
        self._invalidate_bounds()
        return True

    def _invalidate_bounds(self) -> None:
        """Invalidate derived geometry after retained-authority changes."""
        self._bounds_revision = None
        self._content_bounds = None
        self._manipulation_bounds_revision = None
        self._manipulation_bounds = None
        self._source_bounds_revision = None
        self._source_bounds = None

    def _retain_incremental_additive_bounds(
        self,
        item: CoverageItem,
        *,
        previous_source: RasterBounds | None,
        previous_manipulation: QRectF | None,
    ) -> None:
        """Advance cached bounds for one exact non-feathered vector union."""
        if (
            not isinstance(item, VectorCoverageItem)
            or item.combine_mode is not CoverageCombineMode.ADD
            or item.feather_radius > 0.0
        ):
            return
        item_document = CoverageDocument(
            document_id=self.retained.document_id,
            items=(item,),
            revision=self.retained.revision,
        )
        item_manipulation = self._evaluator.vector_content_bounds(item_document)
        item_source = self._evaluator.item_bounds(item)
        revision = self.revision
        self._manipulation_bounds_revision = revision
        self._manipulation_bounds = _united_rectf(
            previous_manipulation,
            item_manipulation,
        )
        self._source_bounds_revision = revision
        self._source_bounds = _united_raster_bounds(previous_source, item_source)


def _empty_snapshot(extent_policy: RasterExtentPolicy) -> CoverageSnapshot:
    """Return canonical empty expanding coverage."""
    return CoverageSnapshot(
        None,
        extent_policy,
        np.zeros((0, 0), dtype=np.uint8),
    )


def _rectf(bounds: RasterBounds) -> QRectF:
    """Return continuous geometry for one integer raster envelope."""
    return QRectF(
        float(bounds.x),
        float(bounds.y),
        float(bounds.width),
        float(bounds.height),
    )


def _continuous_manipulation_bounds(
    raster_bounds: RasterBounds | None,
    retained: CoverageDocument,
    evaluator: CoverageDocumentEvaluator,
) -> tuple[bool, QRectF | None]:
    """Return exact continuous bounds when the ordered expression permits it."""
    items = retained.items
    last_replace = next(
        (
            index
            for index in range(len(items) - 1, -1, -1)
            if items[index].combine_mode is CoverageCombineMode.REPLACE
        ),
        None,
    )
    if last_replace is not None:
        items = items[last_replace:]
        raster_bounds = None
    vector_only = all(
        isinstance(item, VectorCoverageItem) and item.feather_radius == 0.0
        for item in items
    )
    if not vector_only:
        return False, None
    vector_document = CoverageDocument(
        document_id=retained.document_id,
        items=items,
        revision=retained.revision,
    )
    if raster_bounds is None:
        return True, evaluator.vector_content_bounds(vector_document)
    if any(item.combine_mode is not CoverageCombineMode.ADD for item in items):
        return False, None
    vector_bounds = evaluator.vector_content_bounds(vector_document)
    raster_rectangle = _rectf(raster_bounds)
    return (
        True,
        (
            raster_rectangle
            if vector_bounds is None
            else raster_rectangle.united(vector_bounds)
        ),
    )


def _tiles_covering(
    bounds: RasterBounds,
    tile_size: int,
) -> tuple[RasterBounds, ...]:
    """Partition finite bounds into bounded evaluation rectangles."""
    tiles: list[RasterBounds] = []
    for y in range(bounds.y, bounds.bottom, tile_size):
        for x in range(bounds.x, bounds.right, tile_size):
            tiles.append(
                RasterBounds(
                    x,
                    y,
                    min(tile_size, bounds.right - x),
                    min(tile_size, bounds.bottom - y),
                )
            )
    return tuple(tiles)


def _union_bounds(bounds: list[RasterBounds]) -> RasterBounds | None:
    """Return the union of occupied rectangles."""
    result: RasterBounds | None = None
    for candidate in bounds:
        result = candidate if result is None else result.united(candidate)
    return result


def _united_rectf(first: QRectF | None, second: QRectF | None) -> QRectF | None:
    """Return a detached union of optional continuous rectangles."""
    if first is None:
        return None if second is None else QRectF(second)
    return QRectF(first) if second is None else first.united(second)


def _united_raster_bounds(
    first: RasterBounds | None,
    second: RasterBounds | None,
) -> RasterBounds | None:
    """Return the union of optional integer coverage bounds."""
    if first is None:
        return second
    return first if second is None else first.united(second)
