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
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage

from ..scene.raster import RasterBounds, RasterExtentPolicy
from .image_conversion import (
    numpy_to_qimage_argb32,
    numpy_to_qimage_argb32_at_size,
    qimage_to_numpy_argb32,
    qimage_to_numpy_view_argb32,
)
from .sparse_grid import SparseRasterGrid, SparseRasterSnapshot, SparseRasterTile


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
        normalized_image = image.convertToFormat(QImage.Format_ARGB32_Premultiplied)
        self._bounds = bounds or RasterBounds.from_size(normalized_image.size())
        if normalized_image.size() != self._bounds.to_qrect().size():
            raise ValueError("editable raster bounds must match image dimensions")
        self._grid = SparseRasterGrid(channels=4, tile_size=512)
        self._grid.replace(self._bounds, qimage_to_numpy_argb32(normalized_image))
        self._image: QImage | None = normalized_image
        self._tile_images: dict[RasterBounds, QImage] = {}
        self._extent_policy = RasterExtentPolicy(extent_policy)
        self.generation = 0
        self.structure_generation = 0
        self._content_bounds_generation = -1
        self._content_bounds_cache: RasterBounds | None = None

    @classmethod
    def from_sparse_snapshot(cls, snapshot: SparseRasterSnapshot) -> ColorRasterSurface:
        """Build a surface without materializing a sparse snapshot's envelope."""
        if snapshot.bounds is None or snapshot.channels != 4:
            raise ValueError("color raster snapshots require bounds and four channels")
        seed = QImage(1, 1, QImage.Format_ARGB32_Premultiplied)
        seed.fill(0)
        surface = cls(seed)
        surface.replace_with_sparse_snapshot(snapshot)
        surface.generation = 0
        surface.structure_generation = 0
        return surface

    @property
    def bounds(self) -> RasterBounds:
        """Return immutable layer-local storage bounds."""
        return self._bounds

    @property
    def extent_policy(self) -> RasterExtentPolicy:
        """Return the policy controlling future out-of-bounds writes."""
        return self._extent_policy

    @property
    def allocated_bytes(self) -> int:
        """Return sparse authoritative bytes excluding derived image products."""
        with self._lock:
            return self._grid.allocated_bytes

    def revisions(self) -> tuple[int, int]:
        """Return content and structure revisions atomically."""
        with self._lock:
            return self.generation, self.structure_generation

    def versioned_snapshot(self) -> tuple[int, int, ColorRasterSnapshot]:
        """Return revisions and detached state from one synchronized instant."""
        with self._lock:
            return self.generation, self.structure_generation, self.snapshot()

    def versioned_sparse_snapshot(self) -> tuple[int, int, SparseRasterSnapshot]:
        """Return revisions and sparse state from one synchronized instant."""
        with self._lock:
            return (
                self.generation,
                self.structure_generation,
                self._grid.snapshot(self._bounds, self._extent_policy),
            )

    def snapshot_qimage(self) -> QImage:
        """Return a detached full-resolution image snapshot."""
        with self._lock:
            return self._presentation_image_locked().copy()

    def presentation_qimage(self) -> QImage:
        """Return the borrowed read-only render image used on the GUI thread."""
        with self._lock:
            return self._presentation_image_locked()

    def snapshot(self) -> ColorRasterSnapshot:
        """Return detached durable structure and premultiplied pixels."""
        with self._lock:
            return ColorRasterSnapshot(
                self._bounds,
                self._extent_policy,
                self._grid.read(self._bounds),
            )

    def sparse_snapshot(self) -> SparseRasterSnapshot:
        """Return detached sparse durable state without transparent-gap allocation."""
        with self._lock:
            return self._grid.snapshot(self._bounds, self._extent_policy)

    def replace_with_sparse_snapshot(self, snapshot: SparseRasterSnapshot) -> None:
        """Replace complete storage from one four-channel sparse snapshot."""
        if snapshot.bounds is None or snapshot.channels != 4:
            raise ValueError("color raster snapshots require bounds and four channels")
        with self._lock:
            self._grid.restore(snapshot)
            self._bounds = snapshot.bounds
            self._extent_policy = snapshot.extent_policy
            self._image = None
            self._tile_images.clear()
            self.generation += 1
            self.structure_generation += 1

    def replace_with_snapshot(self, snapshot: ColorRasterSnapshot) -> None:
        """Replace complete storage from validated detached state."""
        if not isinstance(snapshot, ColorRasterSnapshot):
            raise TypeError("snapshot must be ColorRasterSnapshot")
        with self._lock:
            self._grid.replace(snapshot.bounds, snapshot.pixels)
            self._image = numpy_to_qimage_argb32(snapshot.pixels)
            self._tile_images.clear()
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
            return self._grid.read(bounds)

    def capture_alpha_occupancy(self, bounds: RasterBounds) -> np.ndarray | None:
        """Return detached binary alpha occupancy for a contained local patch."""
        with self._lock:
            if not self._bounds.contains(bounds):
                return None
            alpha = self._grid.read(bounds)[:, :, 3]
            return np.where(alpha != 0, np.uint8(255), np.uint8(0))

    def content_bounds(self) -> RasterBounds | None:
        """Return revision-cached bounds of nontransparent pixels."""
        with self._lock:
            if self._content_bounds_generation == self.generation:
                return self._content_bounds_cache
            bounds = self._grid.content_bounds()
            self._content_bounds_cache = bounds
            self._content_bounds_generation = self.generation
            return bounds

    def capture_region(self, bounds: RasterBounds) -> np.ndarray:
        """Return a zero-padded BGRA region in layer-local coordinates."""
        with self._lock:
            return self._grid.read(bounds)

    def set_bounds(self, bounds: RasterBounds) -> bool:
        """Crop or pad storage while preserving layer-local pixels."""
        with self._lock:
            if bounds == self._bounds:
                return False
            self._grid.crop(bounds)
            self._bounds = bounds
            self._image = None
            self._tile_images.clear()
            self.generation += 1
            self.structure_generation += 1
            return True

    def ensure_bounds(self, bounds: RasterBounds) -> bool:
        """Enlarge logical unbounded extent without materializing transparent gaps."""
        with self._lock:
            if self._bounds.contains(bounds):
                return False
            self._bounds = self._bounds.united(bounds)
            self._image = None
            self.structure_generation += 1
            return True

    def sparse_tiles(
        self,
        visible_bounds: RasterBounds,
    ) -> tuple[SparseRasterTile, ...]:
        """Return nontransparent tiles clipped to logical and visible extents."""
        with self._lock:
            visible = self._bounds.intersection(visible_bounds)
            if visible is None:
                return ()
            patches: list[SparseRasterTile] = []
            for tile in self._grid.tiles(visible):
                overlap = tile.bounds.intersection(visible)
                if overlap is None:
                    continue
                x = overlap.x - tile.bounds.x
                y = overlap.y - tile.bounds.y
                patches.append(
                    SparseRasterTile(
                        overlap,
                        tile.pixels[
                            y : y + overlap.height,
                            x : x + overlap.width,
                        ],
                    )
                )
            return tuple(patches)

    def sparse_tile_count(self, visible_bounds: RasterBounds) -> int:
        """Return visible allocated tile count without detaching pixels."""
        with self._lock:
            visible = self._bounds.intersection(visible_bounds)
            return 0 if visible is None else self._grid.count_tiles(visible)

    def sampled_qimage(self, scale: float) -> QImage:
        """Return a display sample without materializing transparent gaps."""
        normalized_scale = min(1.0, max(1e-6, float(scale)))
        with self._lock:
            target_size = QSize(
                max(1, round(self._bounds.width * normalized_scale)),
                max(1, round(self._bounds.height * normalized_scale)),
            )
            stride = max(1, int(1.0 / normalized_scale))
            pixels = self._grid.read_strided(self._bounds, stride)
        return numpy_to_qimage_argb32_at_size(pixels, target_size)

    def presentation_tiles(
        self,
        visible_bounds: RasterBounds,
    ) -> tuple[tuple[RasterBounds, RasterBounds, QImage], ...]:
        """Return cached core, bleed bounds, and images for visible tiles."""
        with self._lock:
            visible = self._bounds.intersection(visible_bounds)
            if visible is None:
                return ()
            products: list[tuple[RasterBounds, RasterBounds, QImage]] = []
            for tile_bounds, _pixels in self._grid.borrowed_tiles(visible):
                core_bounds = tile_bounds.intersection(self._bounds)
                if core_bounds is None:
                    continue
                sample_bounds = RasterBounds(
                    core_bounds.x - 1,
                    core_bounds.y - 1,
                    core_bounds.width + 2,
                    core_bounds.height + 2,
                )
                image = self._tile_images.get(core_bounds)
                if image is None:
                    image = numpy_to_qimage_argb32(self._grid.read(sample_bounds))
                    self._tile_images[core_bounds] = image
                products.append((core_bounds, sample_bounds, image))
            return tuple(products)

    def mutate_patch(
        self,
        bounds: RasterBounds,
        mutator: Callable[[np.ndarray], bool],
    ) -> bool:
        """Mutate a contained BGRA view and advance content revision on change."""
        with self._lock:
            if not self._bounds.contains(bounds):
                return False
            pixels = self._grid.read(bounds)
            changed = mutator(pixels)
            if changed:
                self._grid.write(bounds, pixels)
                self._invalidate_tile_images(bounds)
                image = self._image
                if image is not None:
                    image_pixels, backing = qimage_to_numpy_view_argb32(image)
                    if backing.cacheKey() != image.cacheKey():
                        raise RuntimeError(
                            "editable raster surface lost canonical image format"
                        )
                    x = bounds.x - self._bounds.x
                    y = bounds.y - self._bounds.y
                    image_pixels[
                        y : y + bounds.height,
                        x : x + bounds.width,
                    ] = pixels
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

    def _presentation_image_locked(self) -> QImage:
        """Materialize and retain the current logical envelope on demand."""
        image = self._image
        if image is None:
            image = numpy_to_qimage_argb32(self._grid.read(self._bounds))
            self._image = image
        return image

    def _invalidate_tile_images(self, bounds: RasterBounds) -> None:
        """Discard only cached products whose one-pixel samples changed."""
        for core_bounds in tuple(self._tile_images):
            sample_bounds = RasterBounds(
                core_bounds.x - 1,
                core_bounds.y - 1,
                core_bounds.width + 2,
                core_bounds.height + 2,
            )
            if sample_bounds.intersection(bounds) is not None:
                self._tile_images.pop(core_bounds, None)


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
