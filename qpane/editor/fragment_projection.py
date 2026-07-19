#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""One-time projection of floating raster fragments between layer spaces."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QSize, Qt

from ..coverage import CoverageSnapshot
from ..raster.image_conversion import (
    numpy_to_qimage_argb32,
    numpy_to_qimage_grayscale8,
    qimage_to_numpy_argb32,
    qimage_to_numpy_grayscale8,
)
from ..scene.pixel_fragments import RasterPixelFormat, RasterPixelFragment
from ..scene.raster import LayerTransform, RasterBounds


class RasterFragmentProjector:
    """Project a fragment once when committing across layer transforms."""

    def project(
        self,
        fragment: RasterPixelFragment,
        *,
        source_transform: LayerTransform,
        source_delta: tuple[int, int],
        destination_transform: LayerTransform,
    ) -> RasterPixelFragment | None:
        """Return destination-local samples covering the same scene rectangle."""
        moved_bounds = fragment.bounds.translated(*source_delta)
        scene_bounds = source_transform.map_bounds(moved_bounds)
        top_left = destination_transform.inverse_map(
            QPointF(scene_bounds.x, scene_bounds.y)
        )
        bottom_right = destination_transform.inverse_map(
            QPointF(
                scene_bounds.x + scene_bounds.width,
                scene_bounds.y + scene_bounds.height,
            )
        )
        if top_left is None or bottom_right is None:
            return None
        left = round(top_left.x())
        top = round(top_left.y())
        width = max(1, round(scene_bounds.width / destination_transform.scale_x))
        height = max(1, round(scene_bounds.height / destination_transform.scale_y))
        destination_bounds = RasterBounds(left, top, width, height)
        if (
            destination_bounds.width == fragment.bounds.width
            and destination_bounds.height == fragment.bounds.height
        ):
            pixels = fragment.pixels
            coverage_pixels = fragment.coverage.pixels
        else:
            size = QSize(destination_bounds.width, destination_bounds.height)
            if fragment.pixel_format is RasterPixelFormat.COVERAGE8:
                pixels = qimage_to_numpy_grayscale8(
                    numpy_to_qimage_grayscale8(fragment.pixels).scaled(
                        size,
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                pixels = qimage_to_numpy_argb32(
                    numpy_to_qimage_argb32(fragment.pixels).scaled(
                        size,
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            coverage_pixels = qimage_to_numpy_grayscale8(
                numpy_to_qimage_grayscale8(fragment.coverage.pixels).scaled(
                    size,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        coverage = CoverageSnapshot(
            destination_bounds,
            fragment.coverage.extent_policy,
            coverage_pixels,
        )
        return RasterPixelFragment(
            destination_bounds,
            fragment.pixel_format,
            pixels,
            coverage,
        )
