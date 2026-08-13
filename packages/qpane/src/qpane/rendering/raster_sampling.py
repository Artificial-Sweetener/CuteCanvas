#    QPane - High-performance PySide6 image viewer
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
"""Own source-native raster sampling policy and stable device-pixel phase."""

from __future__ import annotations

from math import floor, hypot, isclose

from PySide6.QtGui import QTransform

from ..scene.raster_sampling import RasterExactSampling, RasterPresentationSampling
from .panel_mapping import PanelLayerMapping, PiecewisePanelMapping

NATIVE_RASTER_SAMPLE_SCALE = 1.0
_NEAREST_SOURCE_SCALE = 2.0


def raster_presentation_sampling(
    source_to_panel: PanelLayerMapping,
    device_pixel_ratio: float,
) -> RasterPresentationSampling:
    """Return the preview sampler for one source-to-panel mapping."""
    if device_pixel_ratio <= 0.0:
        raise ValueError("device_pixel_ratio must be positive")
    transforms = (
        tuple(patch.transform for patch in source_to_panel.patches)
        if isinstance(source_to_panel, PiecewisePanelMapping)
        else (source_to_panel,)
    )
    scale_x = max(hypot(transform.m11(), transform.m12()) for transform in transforms)
    scale_y = max(hypot(transform.m21(), transform.m22()) for transform in transforms)
    physical_scale = max(scale_x, scale_y) * device_pixel_ratio
    return raster_presentation_sampling_for_source_scale(physical_scale)


def raster_presentation_sampling_for_source_scale(
    source_native_scale: float,
) -> RasterPresentationSampling:
    """Return the preview sampler relative to the one-source-pixel 1:1 point."""
    if source_native_scale < 0.0:
        raise ValueError("source_native_scale must be non-negative")
    if source_native_scale < _NEAREST_SOURCE_SCALE:
        return RasterPresentationSampling.BILINEAR
    return RasterPresentationSampling.NEAREST


def exact_raster_sampling(
    source_to_panel: QTransform,
    device_pixel_ratio: float,
    *,
    source_native_scale: float | None = None,
) -> RasterExactSampling:
    """Return the exact operation for one settled source projection."""
    presentation = (
        raster_presentation_sampling(source_to_panel, device_pixel_ratio)
        if source_native_scale is None
        else raster_presentation_sampling_for_source_scale(source_native_scale)
    )
    if presentation is RasterPresentationSampling.NEAREST:
        return RasterExactSampling.NEAREST
    if _is_axis_aligned_affine(source_to_panel):
        return RasterExactSampling.LANCZOS3
    return RasterExactSampling.AFFINE_BILINEAR


def raster_sample_scale_limit(
    source_to_panel: PanelLayerMapping,
    device_pixel_ratio: float,
) -> float | None:
    """Return a native-resolution cap only during nearest presentation."""
    if (
        raster_presentation_sampling(source_to_panel, device_pixel_ratio)
        is RasterPresentationSampling.BILINEAR
    ):
        return None
    return NATIVE_RASTER_SAMPLE_SCALE


def device_aligned_raster_transform(
    transform: QTransform,
    device_pixel_ratio: float,
) -> QTransform:
    """Return a transform whose translation has one stable physical-pixel phase."""
    if device_pixel_ratio <= 0.0:
        raise ValueError("device_pixel_ratio must be positive")
    aligned = QTransform(transform)
    physical_x = transform.m31() * device_pixel_ratio
    physical_y = transform.m32() * device_pixel_ratio
    aligned.setMatrix(
        transform.m11(),
        transform.m12(),
        transform.m13(),
        transform.m21(),
        transform.m22(),
        transform.m23(),
        _stable_physical_floor(physical_x) / device_pixel_ratio,
        _stable_physical_floor(physical_y) / device_pixel_ratio,
        transform.m33(),
    )
    return aligned


def _stable_physical_floor(value: float) -> int:
    """Floor a physical coordinate without crossing an integer from float noise."""
    nearest = round(value)
    if isclose(value, nearest, rel_tol=0.0, abs_tol=1e-9):
        return int(nearest)
    return floor(value)


def _is_axis_aligned_affine(transform: QTransform) -> bool:
    """Return whether an invertible affine mapping has no axis mixing."""
    tolerance = 1e-12
    return (
        transform.isAffine()
        and abs(transform.m12()) <= tolerance
        and abs(transform.m21()) <= tolerance
        and abs(transform.m11()) > tolerance
        and abs(transform.m22()) > tolerance
    )
