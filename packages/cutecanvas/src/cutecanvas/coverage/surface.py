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
"""Thread-safe authoritative surfaces for grayscale editing coverage."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeAlias

import numpy as np
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage
from qpane.sdk.raster import qimage_to_numpy_view_grayscale8
from qpane.sdk.scene import RasterBounds

from cutecanvas.types import RasterExtentPolicy

from ..raster.sparse_grid import (
    SparseRasterGrid,
    SparseRasterSnapshot,
    SparseRasterTile,
)


@dataclass(frozen=True, slots=True)
class CoverageSnapshot:
    """Capture authoritative coverage pixels, local bounds, and extent policy."""

    bounds: RasterBounds | None
    extent_policy: RasterExtentPolicy
    pixels: np.ndarray

    def __post_init__(self) -> None:
        """Validate snapshot geometry and detach writable pixel storage."""
        pixels = normalize_coverage_array(self.pixels)
        if self.bounds is None:
            if pixels.size:
                raise ValueError("null mask bounds require empty pixels")
        elif pixels.shape != (self.bounds.height, self.bounds.width):
            raise ValueError("mask snapshot pixels must match local bounds")
        pixels.flags.writeable = False
        object.__setattr__(self, "pixels", pixels)

    def translated(self, delta_x: int, delta_y: int) -> CoverageSnapshot:
        """Return identical coverage shifted in its coordinate space."""
        bounds = self.bounds
        return self.with_bounds(
            None if bounds is None else bounds.translated(delta_x, delta_y),
        )

    def with_bounds(
        self,
        bounds: RasterBounds | None,
        *,
        extent_policy: RasterExtentPolicy | None = None,
    ) -> CoverageSnapshot:
        """Return immutable pixels with replacement coordinate metadata."""
        policy = self.extent_policy if extent_policy is None else extent_policy
        return CoverageSnapshot._adopt_detached(bounds, policy, self.pixels)

    def clipped_to(self, bounds: RasterBounds) -> CoverageSnapshot | None:
        """Return the minimal intersection with ``bounds`` in the same coordinates."""
        current = self.bounds
        if current is None:
            return None
        overlap = current.intersection(bounds)
        if overlap is None:
            return None
        if overlap == current:
            return self
        x = overlap.x - current.x
        y = overlap.y - current.y
        return CoverageSnapshot(
            overlap,
            self.extent_policy,
            self.pixels[y : y + overlap.height, x : x + overlap.width],
        )

    @classmethod
    def _adopt_detached(
        cls,
        bounds: RasterBounds | None,
        extent_policy: RasterExtentPolicy,
        pixels: np.ndarray,
    ) -> CoverageSnapshot:
        """Adopt storage detached from its surface without another full copy."""
        if (
            pixels.dtype != np.uint8
            or pixels.ndim != 2
            or not pixels.flags.c_contiguous
        ):
            raise ValueError("adopted coverage pixels must be contiguous uint8 storage")
        if bounds is None:
            if pixels.size:
                raise ValueError("null coverage bounds require empty pixels")
        elif pixels.shape != (bounds.height, bounds.width):
            raise ValueError("adopted coverage pixels must match local bounds")
        pixels.flags.writeable = False
        snapshot = object.__new__(cls)
        object.__setattr__(snapshot, "bounds", bounds)
        object.__setattr__(snapshot, "extent_policy", extent_policy)
        object.__setattr__(snapshot, "pixels", pixels)
        return snapshot


@dataclass(frozen=True, slots=True)
class WritableCoverageRegion:
    """Describe the layer-local region accepted for one surface write."""

    requested: RasterBounds
    writable: RasterBounds | None
    before_bounds: RasterBounds | None
    after_bounds: RasterBounds | None

    @property
    def expanded(self) -> bool:
        """Return whether accepting the write enlarged surface storage."""
        return self.before_bounds != self.after_bounds


CoverageStateSnapshot: TypeAlias = CoverageSnapshot | SparseRasterSnapshot


def normalize_coverage_array(array: np.ndarray | None) -> np.ndarray:
    """Return a detached contiguous uint8 coverage array."""
    if array is None:
        return np.zeros((0, 0), dtype=np.uint8)
    mask = np.asarray(array)
    if mask.ndim != 2:
        raise ValueError("Mask arrays must be two-dimensional (H, W).")
    if mask.size == 0:
        return np.zeros(mask.shape, dtype=np.uint8)
    if mask.dtype == np.bool_:
        mask = mask.astype(np.uint8) * 255
    elif np.issubdtype(mask.dtype, np.floating):
        safe = np.nan_to_num(mask, nan=0.0, posinf=255.0, neginf=0.0)
        maximum = float(safe.max()) if safe.size else 0.0
        safe = (
            np.clip(safe, 0.0, 1.0) * 255.0
            if maximum <= 1.0
            else np.clip(safe, 0.0, 255.0)
        )
        mask = safe.astype(np.uint8)
    elif mask.dtype != np.uint8:
        mask = np.clip(mask, 0, 255).astype(np.uint8)
    result = np.empty(mask.shape, dtype=np.uint8, order="C")
    np.copyto(result, mask)
    return result


def reframe_coverage_snapshot(
    snapshot: CoverageSnapshot,
    bounds: RasterBounds,
) -> CoverageSnapshot:
    """Return ``snapshot`` padded or cropped to layer-local ``bounds``."""
    replacement = np.zeros((bounds.height, bounds.width), dtype=np.uint8)
    current = snapshot.bounds
    if current is not None:
        overlap = current.intersection(bounds)
        if overlap is not None:
            source_y = overlap.y - current.y
            source_x = overlap.x - current.x
            target_y = overlap.y - bounds.y
            target_x = overlap.x - bounds.x
            replacement[
                target_y : target_y + overlap.height,
                target_x : target_x + overlap.width,
            ] = snapshot.pixels[
                source_y : source_y + overlap.height,
                source_x : source_x + overlap.width,
            ]
    return CoverageSnapshot(
        bounds=bounds,
        extent_policy=snapshot.extent_policy,
        pixels=replacement,
    )


class CoverageSurface:
    """Own synchronized grayscale pixels and detached snapshots."""

    def __init__(
        self,
        buffer: np.ndarray | None = None,
        *,
        bounds: RasterBounds | None = None,
        extent_policy: RasterExtentPolicy = RasterExtentPolicy.FIXED,
    ) -> None:
        """Initialize normalized pixels and their zero-copy Qt view."""
        self._lock = threading.RLock()
        pixels = normalize_coverage_array(buffer)
        self._bounds = self._normalized_bounds(bounds, pixels)
        self._extent_policy = RasterExtentPolicy(extent_policy)
        self._grid = SparseRasterGrid(channels=1, tile_size=512)
        if self._bounds is not None:
            self._grid.replace(self._bounds, pixels)
        self._buffer: np.ndarray | None = pixels
        self._image: QImage | None = self._wrap_buffer(pixels)
        self._snapshot_cache: QImage | None = None
        self._snapshot_generation = -1
        self.generation = 0
        self.structure_generation = 0
        self._content_bounds_generation = -1
        self._content_bounds_cache: RasterBounds | None = None

    @classmethod
    def from_qimage(cls, image: QImage) -> CoverageSurface:
        """Build a surface from a detached image snapshot."""
        if image.isNull():
            return cls()
        grayscale = (
            image
            if image.format() == QImage.Format_Grayscale8
            else image.convertToFormat(QImage.Format_Grayscale8)
        )
        view, _ = qimage_to_numpy_view_grayscale8(grayscale)
        return cls(view)

    @classmethod
    def blank(
        cls,
        size: QSize,
        *,
        extent_policy: RasterExtentPolicy = RasterExtentPolicy.FIXED,
    ) -> CoverageSurface:
        """Create a zero-filled surface with an explicit write-extent policy."""
        if not size.isValid():
            return cls(extent_policy=extent_policy)
        return cls(
            np.zeros((size.height(), size.width()), dtype=np.uint8),
            extent_policy=extent_policy,
        )

    @classmethod
    def from_sparse_snapshot(cls, snapshot: SparseRasterSnapshot) -> CoverageSurface:
        """Build a surface without materializing a sparse snapshot's envelope."""
        surface = cls()
        surface.replace_with_sparse_snapshot(snapshot)
        surface.generation = 0
        surface.structure_generation = 0
        return surface

    def is_null(self) -> bool:
        """Return whether the surface has no pixels."""
        with self._lock:
            return self._bounds is None

    @property
    def bounds(self) -> RasterBounds | None:
        """Return immutable layer-local storage bounds."""
        with self._lock:
            return self._bounds

    @property
    def extent_policy(self) -> RasterExtentPolicy:
        """Return the policy controlling out-of-bounds writes."""
        with self._lock:
            return self._extent_policy

    @property
    def allocated_bytes(self) -> int:
        """Return authoritative sparse bytes excluding derived dense products."""
        with self._lock:
            return self._grid.allocated_bytes

    def set_extent_policy(self, policy: RasterExtentPolicy) -> bool:
        """Replace write-extent policy without changing pixels or bounds."""
        normalized = RasterExtentPolicy(policy)
        with self._lock:
            if normalized is self._extent_policy:
                return False
            self._extent_policy = normalized
            self.structure_generation += 1
            return True

    def snapshot(self) -> CoverageSnapshot:
        """Return a detached structural and pixel snapshot."""
        with self._lock:
            return CoverageSnapshot(
                bounds=self._bounds,
                extent_policy=self._extent_policy,
                pixels=self._dense_locked(),
            )

    def sparse_snapshot(self) -> SparseRasterSnapshot:
        """Return detached sparse state without materializing transparent gaps."""
        with self._lock:
            return self._grid.snapshot(self._bounds, self._extent_policy)

    def state_snapshot(self) -> SparseRasterSnapshot:
        """Return the sparse structural state used by history and persistence."""
        return self.sparse_snapshot()

    def replace_with_sparse_snapshot(self, snapshot: SparseRasterSnapshot) -> None:
        """Replace complete storage from one single-channel sparse snapshot."""
        if snapshot.channels != 1:
            raise ValueError("coverage snapshots require one channel")
        with self._lock:
            self._grid.restore(snapshot)
            self._bounds = snapshot.bounds
            self._extent_policy = snapshot.extent_policy
            self._buffer = None
            self._image = None
            self._mark_changed(structure=True)

    def replace_with_state_snapshot(self, snapshot: CoverageStateSnapshot) -> None:
        """Restore either current sparse state or a legacy dense state."""
        if isinstance(snapshot, SparseRasterSnapshot):
            self.replace_with_sparse_snapshot(snapshot)
        else:
            self.replace_with_snapshot(snapshot)

    def content_bounds(self) -> RasterBounds | None:
        """Return revision-cached bounds of nonzero coverage."""
        with self._lock:
            if self._content_bounds_generation == self.generation:
                return self._content_bounds_cache
            bounds = None if self._bounds is None else self._grid.content_bounds()
            self._content_bounds_cache = bounds
            self._content_bounds_generation = self.generation
            return bounds

    def versioned_snapshot(self) -> tuple[int, int, CoverageSnapshot]:
        """Return content/structure revisions with one atomic detached snapshot."""
        with self._lock:
            return (
                self.generation,
                self.structure_generation,
                CoverageSnapshot(
                    bounds=self._bounds,
                    extent_policy=self._extent_policy,
                    pixels=self._dense_locked(),
                ),
            )

    def versioned_state_snapshot(
        self,
    ) -> tuple[int, int, SparseRasterSnapshot]:
        """Return revisions with sparse structural state from one instant."""
        with self._lock:
            return (
                self.generation,
                self.structure_generation,
                self._grid.snapshot(self._bounds, self._extent_policy),
            )

    def revisions(self) -> tuple[int, int]:
        """Return current content and structure revisions atomically."""
        with self._lock:
            return self.generation, self.structure_generation

    def snapshot_qimage(self) -> QImage:
        """Return a detached, thread-safe image snapshot."""
        with self._lock:
            if self.is_null():
                return QImage()
            if (
                self._snapshot_cache is None
                or self._snapshot_generation != self.generation
            ):
                self._snapshot_cache = self._image_locked().copy()
                self._snapshot_generation = self.generation
            return self._snapshot_cache.copy()

    def snapshot_array(self) -> np.ndarray:
        """Return a detached NumPy snapshot."""
        with self._lock:
            return np.array(self._dense_locked(), copy=True)

    def snapshot_storage_region(
        self,
        region: RasterBounds,
        *,
        stride: int = 1,
    ) -> np.ndarray:
        """Return a detached storage-coordinate region without copying the surface."""
        if not isinstance(region, RasterBounds):
            raise TypeError("region must be RasterBounds")
        normalized_stride = max(1, int(stride))
        with self._lock:
            bounds = self._bounds
            if bounds is None:
                raise ValueError("cannot snapshot a null mask surface")
            storage = RasterBounds(0, 0, bounds.width, bounds.height)
            if not storage.contains(region):
                raise ValueError("storage region must lie within the mask surface")
            local = RasterBounds(
                bounds.x + region.x,
                bounds.y + region.y,
                region.width,
                region.height,
            )
            return np.array(
                self._grid.read_strided(local, normalized_stride),
                copy=True,
                order="C",
            )

    def capture_region(self, region: RasterBounds) -> np.ndarray:
        """Return a zero-padded detached layer-local coverage region."""
        if not isinstance(region, RasterBounds):
            raise TypeError("region must be RasterBounds")
        with self._lock:
            return self._grid.read(region)

    def capture_region_strided(
        self,
        region: RasterBounds,
        stride: int,
    ) -> np.ndarray:
        """Return a density-bounded sample without materializing transparent gaps."""
        if not isinstance(region, RasterBounds):
            raise TypeError("region must be RasterBounds")
        with self._lock:
            return self._grid.read_strided(region, max(1, int(stride)))

    def sparse_tiles(self, visible: RasterBounds) -> tuple[SparseRasterTile, ...]:
        """Return allocated coverage tiles intersecting visible logical storage."""
        if not isinstance(visible, RasterBounds):
            raise TypeError("visible must be RasterBounds")
        with self._lock:
            logical = (
                None if self._bounds is None else self._bounds.intersection(visible)
            )
            return () if logical is None else self._grid.tiles(logical)

    def sparse_tile_count(self, visible: RasterBounds) -> int:
        """Return visible allocated tile count without detaching tile pixels."""
        if not isinstance(visible, RasterBounds):
            raise TypeError("visible must be RasterBounds")
        with self._lock:
            logical = (
                None if self._bounds is None else self._bounds.intersection(visible)
            )
            return 0 if logical is None else self._grid.count_tiles(logical)

    def storage_value(self, x: int, y: int) -> int:
        """Return one storage-coordinate value, or zero outside the surface."""
        with self._lock:
            bounds = self._bounds
            if (
                bounds is None
                or x < 0
                or y < 0
                or x >= bounds.width
                or y >= bounds.height
            ):
                return 0
            return int(
                self._grid.read(RasterBounds(bounds.x + x, bounds.y + y, 1, 1))[0, 0]
            )

    def replace_with_array(self, array: np.ndarray) -> None:
        """Replace authoritative pixels and advance content revision."""
        pixels = normalize_coverage_array(array)
        with self._lock:
            previous_bounds = self._bounds
            origin_x = 0 if self._bounds is None else self._bounds.x
            origin_y = 0 if self._bounds is None else self._bounds.y
            self._bounds = (
                None
                if pixels.size == 0
                else RasterBounds(
                    origin_x,
                    origin_y,
                    pixels.shape[1],
                    pixels.shape[0],
                )
            )
            self._grid.clear()
            if self._bounds is not None:
                self._grid.replace(self._bounds, pixels)
            self._buffer = pixels
            self._image = self._wrap_buffer(pixels)
            self._mark_changed(structure=self._bounds != previous_bounds)

    def replace_with_snapshot(self, snapshot: CoverageSnapshot) -> None:
        """Replace authoritative structure and pixels from ``snapshot``."""
        with self._lock:
            self._buffer = np.array(snapshot.pixels, copy=True, order="C")
            self._bounds = snapshot.bounds
            self._extent_policy = snapshot.extent_policy
            self._grid.clear()
            if self._bounds is not None:
                self._grid.replace(self._bounds, self._buffer)
            self._image = self._wrap_buffer(self._buffer)
            self._mark_changed(structure=True)

    def replace_with_qimage(self, image: QImage) -> None:
        """Replace authoritative pixels from a QImage."""
        if image.isNull():
            self.replace_with_array(np.zeros((0, 0), dtype=np.uint8))
            return
        grayscale = (
            image
            if image.format() == QImage.Format_Grayscale8
            else image.convertToFormat(QImage.Format_Grayscale8)
        )
        view, _ = qimage_to_numpy_view_grayscale8(grayscale)
        self.replace_with_array(view)

    def mutate(self, mutator: Callable[[np.ndarray, QImage], None]) -> None:
        """Run one controlled in-place mutation and advance revision."""
        with self._lock:
            buffer = self._dense_locked()
            image = self._image_locked()
            mutator(buffer, image)
            if self._bounds is not None:
                self._grid.replace(self._bounds, buffer)
            self._mark_changed()

    def mutate_storage_region(
        self,
        region: RasterBounds,
        mutator: Callable[[np.ndarray, QImage], None],
    ) -> None:
        """Mutate one zero-origin storage patch without materializing its envelope."""
        with self._lock:
            bounds = self._bounds
            if bounds is None:
                raise ValueError("cannot mutate a null coverage surface")
            storage = RasterBounds(0, 0, bounds.width, bounds.height)
            if not storage.contains(region):
                raise ValueError("storage region must lie within the coverage surface")
            local = RasterBounds(
                bounds.x + region.x,
                bounds.y + region.y,
                region.width,
                region.height,
            )
            pixels = self._grid.read(local)
            image = self._wrap_buffer(pixels)
            mutator(pixels, image)
            self._grid.write(local, pixels)
            self._buffer = None
            self._image = None
            self._mark_changed()

    def fill(self, value: int) -> None:
        """Fill the surface through the controlled mutation boundary."""
        normalized = QColor(value).red() if isinstance(value, Qt.GlobalColor) else value

        def apply(buffer: np.ndarray, _image: QImage) -> None:
            """Fill the writable canonical buffer with the normalized value."""
            buffer.fill(normalized)

        self.mutate(apply)

    def set_bounds(self, bounds: RasterBounds) -> bool:
        """Pad or crop storage to ``bounds`` while preserving local pixels."""
        if not isinstance(bounds, RasterBounds):
            raise TypeError("bounds must be RasterBounds")
        with self._lock:
            if bounds == self._bounds:
                return False
            self._reframe_locked(bounds)
            self._mark_changed(structure=True)
            return True

    def ensure_writable(self, requested: RasterBounds) -> WritableCoverageRegion:
        """Apply extent policy and return the accepted layer-local write region."""
        if not isinstance(requested, RasterBounds):
            raise TypeError("requested must be RasterBounds")
        with self._lock:
            before = self._bounds
            if before is None:
                if self._extent_policy is RasterExtentPolicy.FIXED:
                    return WritableCoverageRegion(requested, None, None, None)
                self._bounds = requested
                self._buffer = None
                self._image = None
                self._mark_changed(structure=True)
                return WritableCoverageRegion(requested, requested, None, self._bounds)
            if self._extent_policy is RasterExtentPolicy.FIXED:
                return WritableCoverageRegion(
                    requested,
                    before.intersection(requested),
                    before,
                    before,
                )
            if before.contains(requested):
                return WritableCoverageRegion(requested, requested, before, before)
            self._bounds = before.united(requested)
            self._buffer = None
            self._image = None
            self._mark_changed(structure=True)
            return WritableCoverageRegion(requested, requested, before, self._bounds)

    def expand_with_snapshot(
        self,
        requested: RasterBounds,
    ) -> tuple[WritableCoverageRegion, SparseRasterSnapshot | None]:
        """Expand logical storage while retaining sparse prior state for history."""
        if not isinstance(requested, RasterBounds):
            raise TypeError("requested must be RasterBounds")
        with self._lock:
            before = self._bounds
            if self._extent_policy is RasterExtentPolicy.FIXED or (
                before is not None and before.contains(requested)
            ):
                return self.ensure_writable(requested), None
            snapshot = self._grid.snapshot(before, self._extent_policy)
            target = requested if before is None else before.united(requested)
            self._bounds = target
            self._buffer = None
            self._image = None
            self._mark_changed(structure=True)
            return (
                WritableCoverageRegion(requested, requested, before, self._bounds),
                snapshot,
            )

    def storage_rect(self, layer_region: RasterBounds) -> RasterBounds | None:
        """Convert a local region into zero-origin storage coordinates."""
        with self._lock:
            bounds = self._bounds
            if bounds is None:
                return None
            overlap = bounds.intersection(layer_region)
            if overlap is None:
                return None
            return RasterBounds(
                overlap.x - bounds.x,
                overlap.y - bounds.y,
                overlap.width,
                overlap.height,
            )

    def _mark_changed(self, *, structure: bool = False) -> None:
        """Invalidate snapshots and advance authoritative content revision."""
        self._snapshot_cache = None
        self._snapshot_generation = -1
        self.generation += 1
        if structure:
            self.structure_generation += 1

    def _reframe_locked(self, bounds: RasterBounds) -> None:
        """Replace storage bounds under lock while retaining their intersection."""
        self._grid.crop(bounds)
        self._bounds = bounds
        self._buffer = None
        self._image = None

    def _dense_locked(self) -> np.ndarray:
        """Materialize and retain the current logical envelope on demand."""
        buffer = self._buffer
        bounds = self._bounds
        if buffer is None:
            buffer = (
                np.zeros((0, 0), dtype=np.uint8)
                if bounds is None
                else self._grid.read(bounds)
            )
            self._buffer = buffer
            self._image = self._wrap_buffer(buffer)
        return buffer

    def _image_locked(self) -> QImage:
        """Return the QImage view for the current dense materialization."""
        image = self._image
        if image is None:
            self._dense_locked()
            image = self._image
        return QImage() if image is None else image

    @staticmethod
    def _normalized_bounds(
        bounds: RasterBounds | None,
        buffer: np.ndarray,
    ) -> RasterBounds | None:
        """Return bounds matching ``buffer`` or raise for inconsistent input."""
        if buffer.size == 0:
            if bounds is not None:
                raise ValueError("empty mask pixels require null bounds")
            return None
        if bounds is None:
            return RasterBounds(0, 0, buffer.shape[1], buffer.shape[0])
        if buffer.shape != (bounds.height, bounds.width):
            raise ValueError("mask pixels must match local bounds")
        return bounds

    @staticmethod
    def _wrap_buffer(buffer: np.ndarray) -> QImage:
        """Create a private QImage view over owned pixels."""
        if buffer.size == 0:
            return QImage()
        height, width = buffer.shape
        image = QImage(
            buffer.data, width, height, int(buffer.strides[0]), QImage.Format_Grayscale8
        )
        if image.isNull():
            raise RuntimeError("Failed to wrap mask buffer into QImage.")
        return image
