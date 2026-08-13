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
"""Tiled evaluation and content geometry for hybrid coverage documents."""

from __future__ import annotations

import math
from collections.abc import Iterable

import numpy as np
from cutecanvas.painting.compositor import BrushCompositor
from cutecanvas.painting.dab_engine import BrushDabEngine
from cutecanvas.painting.model import BrushOperation
from cutecanvas.painting.regions import BrushDabRegionPlanner
from cutecanvas.types import RasterExtentPolicy
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath
from qpane.sdk.raster import qimage_to_numpy_grayscale8
from qpane.sdk.scene import LayerTransform, RasterBounds
from qpane.sdk.vector import object_path

from .content_bounds import occupied_coverage_bounds
from .document import (
    CoverageDocument,
    CoverageItem,
    RasterCoverageItem,
    StrokeCoverageItem,
    VectorCoverageItem,
)
from .filters import feather_coverage
from .operations import CoverageCombineMode, combine_coverage
from .projection import AffineCoverageResampler
from .surface import CoverageSnapshot


class CoverageDocumentEvaluator:
    """Evaluate authored coverage only inside requested source-local tiles."""

    def __init__(self, *, tile_size: int = 512) -> None:
        """Create reusable rasterization collaborators and bounded caches."""
        if int(tile_size) <= 0:
            raise ValueError("coverage evaluator tile size must be positive")
        self._tile_size = int(tile_size)
        self._resampler = AffineCoverageResampler()
        self._dabs = BrushDabEngine()
        self._dab_regions = BrushDabRegionPlanner()
        self._brush = BrushCompositor()
        self._bounds_cache: dict[object, RasterBounds | None] = {}
        self._vector_bounds_cache: dict[object, QRectF | None] = {}
        self._item_bounds_cache: dict[
            object,
            tuple[tuple[CoverageItem, RasterBounds | None], ...],
        ] = {}
        self._raster_cache: dict[object, CoverageSnapshot] = {}

    def evaluate(
        self,
        document: CoverageDocument,
        bounds: RasterBounds,
    ) -> CoverageSnapshot:
        """Evaluate ``document`` inside one explicit destination rectangle."""
        pixels = np.zeros((bounds.height, bounds.width), dtype=np.uint8)
        for item, item_bounds in self._indexed_items(document):
            if item_bounds is None or item_bounds.intersection(bounds) is None:
                if item.combine_mode in {
                    CoverageCombineMode.REPLACE,
                    CoverageCombineMode.INTERSECT,
                }:
                    pixels.fill(0)
                continue
            incoming = self._evaluate_item(item, bounds)
            pixels = combine_coverage(pixels, incoming, item.combine_mode)
        return CoverageSnapshot._adopt_detached(
            bounds,
            RasterExtentPolicy.EXPAND_ON_WRITE,
            np.ascontiguousarray(pixels),
        )

    def evaluate_item(
        self,
        item: CoverageItem,
        bounds: RasterBounds,
    ) -> np.ndarray:
        """Return one item's raw coverage without applying its combine mode."""
        item_bounds = _item_bounds(item, self._dabs, self._dab_regions)
        if item_bounds is None or item_bounds.intersection(bounds) is None:
            return np.zeros((bounds.height, bounds.width), dtype=np.uint8)
        return self._evaluate_item(item, bounds)

    def content_bounds(self, document: CoverageDocument) -> RasterBounds | None:
        """Return exact nonzero bounds without materializing transparent gaps."""
        key = document.evaluation_token
        if key in self._bounds_cache:
            return self._bounds_cache[key]
        candidate = self._candidate_bounds(document.items)
        if candidate is None:
            self._remember_bounds(key, None)
            return None
        occupied: list[RasterBounds] = []
        for tile in _tiles_covering(candidate, self._tile_size):
            snapshot = self.evaluate(document, tile)
            nonzero = occupied_coverage_bounds(snapshot)
            if nonzero is not None:
                occupied.append(nonzero)
        result = _union_bounds(occupied)
        self._remember_bounds(key, result)
        return result

    def vector_content_bounds(self, document: CoverageDocument) -> QRectF | None:
        """Return exact continuous bounds for a non-feathered vector expression.

        Raises:
            TypeError: If the document contains raster, stroke, or feathered items.
        """
        if any(
            not isinstance(item, VectorCoverageItem) or item.feather_radius > 0.0
            for item in document.items
        ):
            raise TypeError(
                "continuous vector bounds require only non-feathered vector items"
            )
        key = document.evaluation_token
        if key in self._vector_bounds_cache:
            cached = self._vector_bounds_cache[key]
            return None if cached is None else QRectF(cached)
        current = QPainterPath()
        for item in document.items:
            path = item.transform.to_qtransform().map(object_path(item.geometry))
            if item.combine_mode is CoverageCombineMode.REPLACE:
                current = path
            elif item.combine_mode is CoverageCombineMode.ADD:
                current = current.united(path)
            elif item.combine_mode is CoverageCombineMode.SUBTRACT:
                current = current.subtracted(path)
            else:
                current = current.intersected(path)
        bounds = None if current.isEmpty() else current.boundingRect()
        if len(self._vector_bounds_cache) >= 256:
            self._vector_bounds_cache.pop(next(iter(self._vector_bounds_cache)))
        self._vector_bounds_cache[key] = None if bounds is None else QRectF(bounds)
        return None if bounds is None else QRectF(bounds)

    def candidate_bounds(self, document: CoverageDocument) -> RasterBounds | None:
        """Return conservative bounds containing every possible nonzero pixel."""
        return self._candidate_bounds(document.items)

    def item_bounds(self, item: CoverageItem) -> RasterBounds | None:
        """Return conservative content bounds for one retained item."""
        return _item_bounds(item, self._dabs, self._dab_regions)

    def rasterize(self, document: CoverageDocument) -> CoverageSnapshot:
        """Flatten ``document`` to its minimal nonzero raster representation."""
        key = document.evaluation_token
        cached = self._raster_cache.get(key)
        if cached is not None:
            return cached
        candidate = self._candidate_bounds(document.items)
        if candidate is None:
            snapshot = CoverageSnapshot(
                None,
                RasterExtentPolicy.EXPAND_ON_WRITE,
                np.zeros((0, 0), dtype=np.uint8),
            )
        else:
            evaluated = self.evaluate(document, candidate)
            occupied = occupied_coverage_bounds(evaluated)
            snapshot = (
                CoverageSnapshot(
                    None,
                    RasterExtentPolicy.EXPAND_ON_WRITE,
                    np.zeros((0, 0), dtype=np.uint8),
                )
                if occupied is None
                else evaluated.clipped_to(occupied)
            )
            assert snapshot is not None
        self._remember_bounds(key, snapshot.bounds)
        if len(self._raster_cache) >= 64:
            self._raster_cache.pop(next(iter(self._raster_cache)))
        self._raster_cache[key] = snapshot
        return snapshot

    def _evaluate_item(self, item: CoverageItem, bounds: RasterBounds) -> np.ndarray:
        """Return one item's coverage aligned to ``bounds``."""
        if isinstance(item, RasterCoverageItem):
            return self._evaluate_raster(item, bounds)
        if isinstance(item, VectorCoverageItem):
            return self._evaluate_vector(item, bounds)
        return self._evaluate_stroke(item, bounds)

    def _evaluate_raster(
        self,
        item: RasterCoverageItem,
        bounds: RasterBounds,
    ) -> np.ndarray:
        """Project one immutable raster item through its affine transform."""
        snapshot = item.coverage
        if snapshot.bounds is None:
            return np.zeros((bounds.height, bounds.width), dtype=np.uint8)
        if item.transform == LayerTransform():
            return _copy_overlap(snapshot, bounds)
        return self._resampler.project(
            snapshot,
            item.transform,
            bounds,
            extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
        ).pixels

    def _evaluate_vector(
        self,
        item: VectorCoverageItem,
        bounds: RasterBounds,
    ) -> np.ndarray:
        """Rasterize retained semantic vector geometry for one tile."""
        padding = math.ceil(item.feather_radius * 3.0)
        render_bounds = (
            RasterBounds(
                bounds.x - padding,
                bounds.y - padding,
                bounds.width + padding * 2,
                bounds.height + padding * 2,
            )
            if padding
            else bounds
        )
        image = QImage(
            render_bounds.width,
            render_bounds.height,
            QImage.Format_Grayscale8,
        )
        image.fill(0)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255))
        path = item.transform.to_qtransform().map(object_path(item.geometry))
        painter.translate(-render_bounds.x, -render_bounds.y)
        painter.drawPath(path)
        painter.end()
        pixels = qimage_to_numpy_grayscale8(image)
        if item.feather_radius > 0.0:
            pixels = feather_coverage(pixels, item.feather_radius)
        if not padding:
            return pixels
        return np.ascontiguousarray(
            pixels[padding : padding + bounds.height, padding : padding + bounds.width]
        )

    def _evaluate_stroke(
        self,
        item: StrokeCoverageItem,
        bounds: RasterBounds,
    ) -> np.ndarray:
        """Replay deterministic brush segments and project their authored result."""
        dabs = tuple(
            dab for segment in item.segments for dab in self._dabs.segment_dabs(segment)
        )
        source_bounds = self._dab_regions.bounds(dabs)
        if source_bounds is None:
            return np.zeros((bounds.height, bounds.width), dtype=np.uint8)
        if item.transform == LayerTransform():
            return self._brush.render_coverage_dabs(
                before=np.zeros((bounds.height, bounds.width), dtype=np.uint8),
                patch_bounds=bounds.to_qrect(),
                operation=BrushOperation.PAINT,
                dabs=dabs,
            )
        pixels = np.zeros((source_bounds.height, source_bounds.width), dtype=np.uint8)
        rendered = self._brush.render_coverage_dabs(
            before=pixels,
            patch_bounds=source_bounds.to_qrect(),
            operation=BrushOperation.PAINT,
            dabs=dabs,
        )
        snapshot = CoverageSnapshot(
            source_bounds,
            RasterExtentPolicy.EXPAND_ON_WRITE,
            rendered,
        )
        return self._resampler.project(
            snapshot,
            item.transform,
            bounds,
            extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
        ).pixels

    def _candidate_bounds(self, items: tuple[CoverageItem, ...]) -> RasterBounds | None:
        """Return conservative finite bounds for tiled exact evaluation."""
        current: RasterBounds | None = None
        for item in items:
            bounds = _item_bounds(item, self._dabs, self._dab_regions)
            if item.combine_mode is CoverageCombineMode.REPLACE:
                current = bounds
            elif item.combine_mode is CoverageCombineMode.INTERSECT:
                current = (
                    None
                    if current is None or bounds is None
                    else current.intersection(bounds)
                )
            elif item.combine_mode is CoverageCombineMode.ADD and bounds is not None:
                current = bounds if current is None else current.united(bounds)
        return current

    def _remember_bounds(
        self,
        key: object,
        bounds: RasterBounds | None,
    ) -> None:
        """Retain a small revision-keyed content-bounds cache."""
        if len(self._bounds_cache) >= 256:
            self._bounds_cache.pop(next(iter(self._bounds_cache)))
        self._bounds_cache[key] = bounds

    def _indexed_items(
        self,
        document: CoverageDocument,
    ) -> tuple[tuple[CoverageItem, RasterBounds | None], ...]:
        """Return cached conservative item bounds for tiled culling."""
        key = document.evaluation_token
        cached = self._item_bounds_cache.get(key)
        if cached is not None:
            return cached
        indexed = tuple(
            (item, _item_bounds(item, self._dabs, self._dab_regions))
            for item in document.items
        )
        if len(self._item_bounds_cache) >= 64:
            self._item_bounds_cache.pop(next(iter(self._item_bounds_cache)))
        self._item_bounds_cache[key] = indexed
        return indexed


def _item_bounds(
    item: CoverageItem,
    dabs: BrushDabEngine,
    regions: BrushDabRegionPlanner,
) -> RasterBounds | None:
    """Return conservative transformed bounds for one authored item."""
    if isinstance(item, RasterCoverageItem):
        source = occupied_coverage_bounds(item.coverage)
    elif isinstance(item, VectorCoverageItem):
        rectangle = (
            item.transform.to_qtransform()
            .map(object_path(item.geometry))
            .boundingRect()
        )
        margin = item.feather_radius * 3.0
        source = _raster_bounds(rectangle.adjusted(-margin, -margin, margin, margin))
        return source
    else:
        resolved = tuple(
            dab for segment in item.segments for dab in dabs.segment_dabs(segment)
        )
        source = regions.bounds(resolved)
    return None if source is None else _map_bounds(source, item.transform)


def _map_bounds(bounds: RasterBounds, transform: LayerTransform) -> RasterBounds:
    """Map integer source bounds through an affine transform conservatively."""
    rectangle = transform.to_qtransform().mapRect(QRectF(bounds.to_qrect()))
    return _raster_bounds(rectangle)


def _raster_bounds(rectangle: QRectF) -> RasterBounds | None:
    """Convert positive finite floating bounds into enclosing integer bounds."""
    if rectangle.isEmpty() or not all(
        math.isfinite(value)
        for value in (
            rectangle.left(),
            rectangle.top(),
            rectangle.right(),
            rectangle.bottom(),
        )
    ):
        return None
    left = math.floor(rectangle.left())
    top = math.floor(rectangle.top())
    right = math.ceil(rectangle.right())
    bottom = math.ceil(rectangle.bottom())
    return RasterBounds(left, top, max(1, right - left), max(1, bottom - top))


def _copy_overlap(snapshot: CoverageSnapshot, bounds: RasterBounds) -> np.ndarray:
    """Copy one aligned snapshot into explicit destination bounds."""
    result = np.zeros((bounds.height, bounds.width), dtype=np.uint8)
    source = snapshot.bounds
    if source is None:
        return result
    overlap = source.intersection(bounds)
    if overlap is None:
        return result
    source_x = overlap.x - source.x
    source_y = overlap.y - source.y
    target_x = overlap.x - bounds.x
    target_y = overlap.y - bounds.y
    result[
        target_y : target_y + overlap.height, target_x : target_x + overlap.width
    ] = snapshot.pixels[
        source_y : source_y + overlap.height,
        source_x : source_x + overlap.width,
    ]
    return result


def _tiles_covering(bounds: RasterBounds, tile_size: int) -> Iterable[RasterBounds]:
    """Yield fixed-size tiles clipped to finite candidate bounds."""
    for top in range(bounds.y, bounds.bottom, tile_size):
        for left in range(bounds.x, bounds.right, tile_size):
            yield RasterBounds(
                left,
                top,
                min(tile_size, bounds.right - left),
                min(tile_size, bounds.bottom - top),
            )


def _union_bounds(bounds: Iterable[RasterBounds]) -> RasterBounds | None:
    """Return the union of zero or more integer rectangles."""
    result: RasterBounds | None = None
    for candidate in bounds:
        result = candidate if result is None else result.united(candidate)
    return result
