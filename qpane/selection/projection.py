#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Projection of layer-local coverage into composition scene coordinates."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QImage, QPainter

from ..coverage import CoverageSnapshot
from ..raster.image_conversion import (
    numpy_to_qimage_grayscale8,
    qimage_to_numpy_grayscale8,
)
from ..scene.raster import LayerTransform, RasterBounds, RasterExtentPolicy
from .compositor import trim_selection_coverage


class LayerCoverageProjector:
    """Map axis-aligned source coverage into minimal scene-space storage."""

    def project(
        self,
        coverage: CoverageSnapshot,
        transform: LayerTransform,
    ) -> CoverageSnapshot | None:
        """Return antialiased scene coverage for one layer-local snapshot."""
        source_bounds = coverage.bounds
        if source_bounds is None:
            return None
        integer_translation = _unit_integer_translation(transform)
        if integer_translation is not None:
            return coverage.with_bounds(
                source_bounds.translated(*integer_translation),
                extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
            )
        placement = transform.map_bounds(source_bounds)
        left = math.floor(placement.x)
        top = math.floor(placement.y)
        right = math.ceil(placement.x + placement.width)
        bottom = math.ceil(placement.y + placement.height)
        if right <= left or bottom <= top:
            return None
        scene_bounds = RasterBounds(left, top, right - left, bottom - top)
        target = QImage(
            scene_bounds.width,
            scene_bounds.height,
            QImage.Format_Grayscale8,
        )
        target.fill(0)
        painter = QPainter(target)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(
            QRectF(
                placement.x - left,
                placement.y - top,
                placement.width,
                placement.height,
            ),
            numpy_to_qimage_grayscale8(coverage.pixels),
        )
        painter.end()
        return trim_selection_coverage(
            CoverageSnapshot(
                bounds=scene_bounds,
                extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
                pixels=qimage_to_numpy_grayscale8(target),
            )
        )

    def project_to_layer(
        self,
        coverage: CoverageSnapshot,
        transform: LayerTransform,
        layer_bounds: RasterBounds | None = None,
    ) -> CoverageSnapshot | None:
        """Project scene coverage into bounded or unbounded layer coordinates."""
        scene_bounds = coverage.bounds
        if scene_bounds is None:
            return None
        unbounded = layer_bounds is None
        integer_translation = _unit_integer_translation(transform)
        if integer_translation is not None:
            return _project_integer_translation_to_layer(
                coverage,
                integer_translation,
                layer_bounds,
                unbounded=unbounded,
            )
        top_left = transform.inverse_map(
            QPointF(float(scene_bounds.x), float(scene_bounds.y))
        )
        bottom_right = transform.inverse_map(
            QPointF(float(scene_bounds.right), float(scene_bounds.bottom))
        )
        if top_left is None or bottom_right is None:
            return None
        left = math.floor(min(top_left.x(), bottom_right.x()))
        top = math.floor(min(top_left.y(), bottom_right.y()))
        right = math.ceil(max(top_left.x(), bottom_right.x()))
        bottom = math.ceil(max(top_left.y(), bottom_right.y()))
        if right <= left or bottom <= top:
            return None
        requested_bounds = RasterBounds(left, top, right - left, bottom - top)
        destination_bounds = (
            requested_bounds
            if layer_bounds is None
            else requested_bounds.intersection(layer_bounds)
        )
        if destination_bounds is None:
            return None
        target_rect = QRectF(
            top_left.x() - destination_bounds.x,
            top_left.y() - destination_bounds.y,
            bottom_right.x() - top_left.x(),
            bottom_right.y() - top_left.y(),
        )
        target = QImage(
            destination_bounds.width,
            destination_bounds.height,
            QImage.Format_Grayscale8,
        )
        target.fill(0)
        painter = QPainter(target)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(
            target_rect,
            numpy_to_qimage_grayscale8(coverage.pixels),
        )
        painter.end()
        return trim_selection_coverage(
            CoverageSnapshot(
                bounds=destination_bounds,
                extent_policy=(
                    RasterExtentPolicy.EXPAND_ON_WRITE
                    if unbounded
                    else RasterExtentPolicy.FIXED
                ),
                pixels=qimage_to_numpy_grayscale8(target),
            )
        )


def _unit_integer_translation(transform: LayerTransform) -> tuple[int, int] | None:
    """Return integral translation for the lossless unit-scale projection path."""
    translate_x = round(transform.translate_x)
    translate_y = round(transform.translate_y)
    if (
        transform.scale_x != 1.0
        or transform.scale_y != 1.0
        or not math.isclose(transform.translate_x, translate_x, abs_tol=1e-9)
        or not math.isclose(transform.translate_y, translate_y, abs_tol=1e-9)
    ):
        return None
    return translate_x, translate_y


def _project_integer_translation_to_layer(
    coverage: CoverageSnapshot,
    translation: tuple[int, int],
    layer_bounds: RasterBounds | None,
    *,
    unbounded: bool,
) -> CoverageSnapshot | None:
    """Map unit-scale coverage by metadata and crop only when bounds require it."""
    scene_bounds = coverage.bounds
    if scene_bounds is None:
        return None
    local_bounds = scene_bounds.translated(-translation[0], -translation[1])
    destination = (
        local_bounds
        if layer_bounds is None
        else local_bounds.intersection(layer_bounds)
    )
    if destination is None:
        return None
    policy = (
        RasterExtentPolicy.EXPAND_ON_WRITE if unbounded else RasterExtentPolicy.FIXED
    )
    if destination == local_bounds:
        return coverage.with_bounds(destination, extent_policy=policy)
    source_local = destination.translated(*translation)
    source_x = source_local.x - scene_bounds.x
    source_y = source_local.y - scene_bounds.y
    return trim_selection_coverage(
        CoverageSnapshot(
            destination,
            policy,
            coverage.pixels[
                source_y : source_y + destination.height,
                source_x : source_x + destination.width,
            ],
        )
    )
