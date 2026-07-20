#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Source-neutral affine projection of grayscale coverage snapshots."""

from __future__ import annotations

from PySide6.QtGui import QImage

from ..raster.affine_resampling import AffineImageResampler
from ..raster.image_conversion import (
    numpy_to_qimage_grayscale8,
    qimage_to_numpy_grayscale8,
)
from ..scene.affine import LayerTransform
from ..scene.raster import RasterBounds, RasterExtentPolicy
from .surface import CoverageSnapshot


class AffineCoverageResampler:
    """Resample coverage between coordinate spaces using one affine mapping."""

    def __init__(self) -> None:
        """Create the shared Qt image-affine projection primitive."""
        self._images = AffineImageResampler()

    def project(
        self,
        snapshot: CoverageSnapshot,
        transform: LayerTransform,
        destination_bounds: RasterBounds,
        *,
        extent_policy: RasterExtentPolicy,
        smooth: bool = True,
    ) -> CoverageSnapshot:
        """Project source-coordinate pixels into explicit destination bounds."""
        source_bounds = snapshot.bounds
        if source_bounds is None:
            target = QImage(
                destination_bounds.width,
                destination_bounds.height,
                QImage.Format_Grayscale8,
            )
            target.fill(0)
        else:
            target = self._images.project(
                numpy_to_qimage_grayscale8(snapshot.pixels),
                source_bounds=source_bounds,
                transform=transform,
                destination_bounds=destination_bounds,
                image_format=QImage.Format_Grayscale8,
                smooth=smooth,
            )
        return CoverageSnapshot(
            destination_bounds,
            extent_policy,
            qimage_to_numpy_grayscale8(target),
        )
