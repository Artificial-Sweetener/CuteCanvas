#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Thread-safe authoritative surfaces for grayscale editing coverage."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage

from ..raster.image_conversion import qimage_to_numpy_view_grayscale8
from ..scene.raster import RasterBounds, RasterExtentPolicy


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
        self._buffer = normalize_coverage_array(buffer)
        self._bounds = self._normalized_bounds(bounds, self._buffer)
        self._extent_policy = RasterExtentPolicy(extent_policy)
        self._image = self._wrap_buffer(self._buffer)
        self._snapshot_cache: QImage | None = None
        self._snapshot_generation = -1
        self.generation = 0
        self.structure_generation = 0

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
    def blank(cls, size: QSize) -> CoverageSurface:
        """Create a zero-filled surface of ``size``."""
        if not size.isValid():
            return cls()
        return cls(np.zeros((size.height(), size.width()), dtype=np.uint8))

    def is_null(self) -> bool:
        """Return whether the surface has no pixels."""
        return self._buffer.size == 0

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
                pixels=self._buffer,
            )

    def versioned_snapshot(self) -> tuple[int, int, CoverageSnapshot]:
        """Return content/structure revisions with one atomic detached snapshot."""
        with self._lock:
            return (
                self.generation,
                self.structure_generation,
                CoverageSnapshot(
                    bounds=self._bounds,
                    extent_policy=self._extent_policy,
                    pixels=self._buffer,
                ),
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
                self._snapshot_cache = self._image.copy()
                self._snapshot_generation = self.generation
            return self._snapshot_cache.copy()

    def snapshot_array(self) -> np.ndarray:
        """Return a detached NumPy snapshot."""
        with self._lock:
            return np.array(self._buffer, copy=True)

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
            if self._buffer.size == 0:
                raise ValueError("cannot snapshot a null mask surface")
            storage = RasterBounds(0, 0, self._buffer.shape[1], self._buffer.shape[0])
            if not storage.contains(region):
                raise ValueError("storage region must lie within the mask surface")
            return np.array(
                self._buffer[
                    region.y : region.y + region.height : normalized_stride,
                    region.x : region.x + region.width : normalized_stride,
                ],
                copy=True,
                order="C",
            )

    def storage_value(self, x: int, y: int) -> int:
        """Return one storage-coordinate value, or zero outside the surface."""
        with self._lock:
            height, width = self._buffer.shape
            if x < 0 or y < 0 or x >= width or y >= height:
                return 0
            return int(self._buffer[y, x])

    def replace_with_array(self, array: np.ndarray) -> None:
        """Replace authoritative pixels and advance content revision."""
        pixels = normalize_coverage_array(array)
        with self._lock:
            previous_bounds = self._bounds
            origin_x = 0 if self._bounds is None else self._bounds.x
            origin_y = 0 if self._bounds is None else self._bounds.y
            self._buffer = pixels
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
            self._image = self._wrap_buffer(self._buffer)
            self._mark_changed(structure=self._bounds != previous_bounds)

    def replace_with_snapshot(self, snapshot: CoverageSnapshot) -> None:
        """Replace authoritative structure and pixels from ``snapshot``."""
        with self._lock:
            self._buffer = np.array(snapshot.pixels, copy=True, order="C")
            self._bounds = snapshot.bounds
            self._extent_policy = snapshot.extent_policy
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
            mutator(self._buffer, self._image)
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
                self._reframe_locked(requested)
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
            self._reframe_locked(before.united(requested))
            self._mark_changed(structure=True)
            return WritableCoverageRegion(requested, requested, before, self._bounds)

    def expand_with_snapshot(
        self,
        requested: RasterBounds,
    ) -> tuple[WritableCoverageRegion, CoverageSnapshot | None]:
        """Expand storage while adopting the detached prior buffer for history."""
        if not isinstance(requested, RasterBounds):
            raise TypeError("requested must be RasterBounds")
        with self._lock:
            before = self._bounds
            if self._extent_policy is not RasterExtentPolicy.EXPAND_ON_WRITE or (
                before is not None and before.contains(requested)
            ):
                return self.ensure_writable(requested), None
            old_buffer = self._buffer
            snapshot = CoverageSnapshot._adopt_detached(
                before,
                self._extent_policy,
                old_buffer,
            )
            target = requested if before is None else before.united(requested)
            self._reframe_locked(target)
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
        replacement = np.zeros((bounds.height, bounds.width), dtype=np.uint8)
        current = self._bounds
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
                ] = self._buffer[
                    source_y : source_y + overlap.height,
                    source_x : source_x + overlap.width,
                ]
        self._buffer = replacement
        self._bounds = bounds
        self._image = self._wrap_buffer(self._buffer)

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
