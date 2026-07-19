#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Structure-aware raster patch transitions shared by pixel edit domains."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .raster import RasterBounds


@dataclass(frozen=True, slots=True)
class RasterPixelTransition:
    """Capture the minimum pixels and surface bounds needed for exact replay."""

    patch_bounds: RasterBounds
    before_surface_bounds: RasterBounds
    after_surface_bounds: RasterBounds
    before_pixels: np.ndarray
    after_pixels: np.ndarray

    def __post_init__(self) -> None:
        """Detach retained patches and validate their shared geometry."""
        expected = (self.patch_bounds.height, self.patch_bounds.width)
        before = np.array(self.before_pixels, copy=True, order="C")
        after = np.array(self.after_pixels, copy=True, order="C")
        if before.shape[:2] != expected or after.shape != before.shape:
            raise ValueError("pixel transition patches must share patch bounds")
        before.flags.writeable = False
        after.flags.writeable = False
        object.__setattr__(self, "before_pixels", before)
        object.__setattr__(self, "after_pixels", after)

    @classmethod
    def _adopt_detached(
        cls,
        patch_bounds: RasterBounds,
        before_surface_bounds: RasterBounds,
        after_surface_bounds: RasterBounds,
        before_pixels: np.ndarray,
        after_pixels: np.ndarray,
    ) -> RasterPixelTransition:
        """Adopt validated detached patches without duplicating history storage."""
        expected = (patch_bounds.height, patch_bounds.width)
        if (
            before_pixels.shape[:2] != expected
            or after_pixels.shape != before_pixels.shape
            or before_pixels.dtype != np.uint8
            or after_pixels.dtype != np.uint8
            or not before_pixels.flags.c_contiguous
            or not after_pixels.flags.c_contiguous
        ):
            raise ValueError("adopted transition patches must be contiguous uint8")
        before_pixels.flags.writeable = False
        after_pixels.flags.writeable = False
        transition = object.__new__(cls)
        object.__setattr__(transition, "patch_bounds", patch_bounds)
        object.__setattr__(
            transition,
            "before_surface_bounds",
            before_surface_bounds,
        )
        object.__setattr__(transition, "after_surface_bounds", after_surface_bounds)
        object.__setattr__(transition, "before_pixels", before_pixels)
        object.__setattr__(transition, "after_pixels", after_pixels)
        return transition

    @property
    def retained_bytes(self) -> int:
        """Return bytes retained by the before and after patches."""
        return int(self.before_pixels.nbytes + self.after_pixels.nbytes)
