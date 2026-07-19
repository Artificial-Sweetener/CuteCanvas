#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Thread-safe authoritative storage for editable premultiplied color rasters."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from PySide6.QtGui import QImage

from ..scene.raster import RasterBounds, RasterExtentPolicy
from .image_conversion import (
    numpy_to_qimage_argb32,
    qimage_to_numpy_argb32,
    qimage_to_numpy_view_argb32,
)


@dataclass(frozen=True, slots=True)
class ColorRasterSnapshot:
    """Detached durable state for one editable color raster."""

    bounds: RasterBounds
    extent_policy: RasterExtentPolicy
    pixels: np.ndarray

    def __post_init__(self) -> None:
        """Validate and detach premultiplied BGRA storage."""
        pixels = np.asarray(self.pixels)
        expected = (self.bounds.height, self.bounds.width, 4)
        if pixels.dtype != np.uint8 or pixels.shape != expected:
            raise ValueError(f"color raster pixels must be uint8 with shape {expected}")
        object.__setattr__(self, "pixels", np.array(pixels, copy=True, order="C"))


class ColorRasterSurface:
    """Own editable ARGB pixels, local bounds, policy, and revisions."""

    def __init__(
        self,
        image: QImage,
        *,
        bounds: RasterBounds | None = None,
        extent_policy: RasterExtentPolicy = RasterExtentPolicy.FIXED,
    ) -> None:
        """Detach normalized image storage and validate local bounds."""
        if image.isNull():
            raise ValueError("editable raster image must not be null")
        self._lock = threading.RLock()
        self._image = image.convertToFormat(QImage.Format_ARGB32_Premultiplied)
        self._bounds = bounds or RasterBounds.from_size(self._image.size())
        if self._image.size() != self._bounds.to_qrect().size():
            raise ValueError("editable raster bounds must match image dimensions")
        self._extent_policy = RasterExtentPolicy(extent_policy)
        self.generation = 0
        self.structure_generation = 0

    @property
    def bounds(self) -> RasterBounds:
        """Return immutable layer-local storage bounds."""
        return self._bounds

    @property
    def extent_policy(self) -> RasterExtentPolicy:
        """Return the policy controlling future out-of-bounds writes."""
        return self._extent_policy

    def revisions(self) -> tuple[int, int]:
        """Return content and structure revisions atomically."""
        with self._lock:
            return self.generation, self.structure_generation

    def versioned_snapshot(self) -> tuple[int, int, ColorRasterSnapshot]:
        """Return revisions and detached state from one synchronized instant."""
        with self._lock:
            return self.generation, self.structure_generation, self.snapshot()

    def snapshot_qimage(self) -> QImage:
        """Return a detached full-resolution image snapshot."""
        with self._lock:
            return self._image.copy()

    def snapshot(self) -> ColorRasterSnapshot:
        """Return detached durable structure and premultiplied pixels."""
        with self._lock:
            return ColorRasterSnapshot(
                self._bounds,
                self._extent_policy,
                qimage_to_numpy_argb32(self._image),
            )

    def replace_with_snapshot(self, snapshot: ColorRasterSnapshot) -> None:
        """Replace complete storage from validated detached state."""
        if not isinstance(snapshot, ColorRasterSnapshot):
            raise TypeError("snapshot must be ColorRasterSnapshot")
        with self._lock:
            self._image = numpy_to_qimage_argb32(snapshot.pixels)
            self._bounds = snapshot.bounds
            self._extent_policy = snapshot.extent_policy
            self.generation += 1
            self.structure_generation += 1

    def set_extent_policy(self, policy: RasterExtentPolicy) -> bool:
        """Replace write policy without changing pixels or bounds."""
        normalized = RasterExtentPolicy(policy)
        with self._lock:
            if normalized is self._extent_policy:
                return False
            self._extent_policy = normalized
            self.structure_generation += 1
            return True

    def capture_patch(self, bounds: RasterBounds) -> np.ndarray | None:
        """Return detached BGRA pixels for a contained local patch."""
        with self._lock:
            if not self._bounds.contains(bounds):
                return None
            image = self._image.copy(
                bounds.x - self._bounds.x,
                bounds.y - self._bounds.y,
                bounds.width,
                bounds.height,
            )
            return qimage_to_numpy_argb32(image)

    def capture_region(self, bounds: RasterBounds) -> np.ndarray:
        """Return a zero-padded BGRA region in layer-local coordinates."""
        pixels = np.zeros((bounds.height, bounds.width, 4), dtype=np.uint8)
        with self._lock:
            overlap = self._bounds.intersection(bounds)
            if overlap is None:
                return pixels
            source = self._image.copy(
                overlap.x - self._bounds.x,
                overlap.y - self._bounds.y,
                overlap.width,
                overlap.height,
            )
            source_pixels = qimage_to_numpy_argb32(source)
            target_x = overlap.x - bounds.x
            target_y = overlap.y - bounds.y
            pixels[
                target_y : target_y + overlap.height,
                target_x : target_x + overlap.width,
            ] = source_pixels
        return pixels

    def set_bounds(self, bounds: RasterBounds) -> bool:
        """Crop or pad storage while preserving layer-local pixels."""
        with self._lock:
            if bounds == self._bounds:
                return False
            snapshot = ColorRasterSnapshot(
                self._bounds,
                self._extent_policy,
                qimage_to_numpy_argb32(self._image),
            )
            replacement = reframe_color_raster_snapshot(snapshot, bounds)
            self._image = numpy_to_qimage_argb32(replacement.pixels)
            self._bounds = bounds
            self.generation += 1
            self.structure_generation += 1
            return True

    def mutate_patch(
        self,
        bounds: RasterBounds,
        mutator: Callable[[np.ndarray], bool],
    ) -> bool:
        """Mutate a contained BGRA view and advance content revision on change."""
        with self._lock:
            if not self._bounds.contains(bounds):
                return False
            pixels, backing = qimage_to_numpy_view_argb32(self._image)
            if backing.cacheKey() != self._image.cacheKey():
                raise RuntimeError(
                    "editable raster surface lost canonical image format"
                )
            x = bounds.x - self._bounds.x
            y = bounds.y - self._bounds.y
            changed = mutator(pixels[y : y + bounds.height, x : x + bounds.width])
            if changed:
                self.generation += 1
            return changed

    def restore_patch(self, bounds: RasterBounds, pixels: np.ndarray) -> bool:
        """Restore detached BGRA patch pixels into canonical storage."""
        if pixels.shape != (bounds.height, bounds.width, 4):
            return False

        def restore(destination: np.ndarray) -> bool:
            """Copy retained patch pixels into the writable view."""
            np.copyto(destination, pixels)
            return True

        return self.mutate_patch(bounds, restore)


def reframe_color_raster_snapshot(
    snapshot: ColorRasterSnapshot,
    bounds: RasterBounds,
) -> ColorRasterSnapshot:
    """Crop or pad detached pixels while retaining local coordinates."""
    if bounds == snapshot.bounds:
        return snapshot
    pixels = np.zeros((bounds.height, bounds.width, 4), dtype=np.uint8)
    overlap = bounds.intersection(snapshot.bounds)
    if overlap is not None:
        source_x = overlap.x - snapshot.bounds.x
        source_y = overlap.y - snapshot.bounds.y
        target_x = overlap.x - bounds.x
        target_y = overlap.y - bounds.y
        pixels[
            target_y : target_y + overlap.height,
            target_x : target_x + overlap.width,
        ] = snapshot.pixels[
            source_y : source_y + overlap.height,
            source_x : source_x + overlap.width,
        ]
    return ColorRasterSnapshot(bounds, snapshot.extent_policy, pixels)
