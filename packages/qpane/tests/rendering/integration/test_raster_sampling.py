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
"""Tests for shared raster sampling policy and stable nearest-neighbor phase."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QTransform

from qpane.rendering.raster_sampling import (
    device_aligned_raster_transform,
    exact_raster_sampling,
    raster_presentation_sampling,
    raster_presentation_sampling_for_source_scale,
    raster_sample_scale_limit,
)
from qpane.scene.raster_sampling import RasterExactSampling, RasterPresentationSampling


@pytest.mark.parametrize(
    ("translation", "device_pixel_ratio", "expected"),
    (
        (-75.5, 1.0, -76.0),
        (-39.5, 1.0, -40.0),
        (12.75, 2.0, 12.5),
        (-12.25, 2.0, -12.5),
        (-34.666666666666686, 1.5, -34.666666666666664),
    ),
)
def test_device_aligned_transform_has_stable_physical_phase(
    translation: float,
    device_pixel_ratio: float,
    expected: float,
) -> None:
    """Translations should floor consistently on both sides of the origin."""
    transform = QTransform()
    transform.translate(translation, translation)

    aligned = device_aligned_raster_transform(transform, device_pixel_ratio)

    assert aligned.m31() == pytest.approx(expected)
    assert aligned.m32() == pytest.approx(expected)


@pytest.mark.parametrize(
    ("logical_scale", "device_pixel_ratio", "expected"),
    (
        (1.99, 1.0, RasterPresentationSampling.BILINEAR),
        (2.0, 1.0, RasterPresentationSampling.NEAREST),
        (0.99, 2.0, RasterPresentationSampling.BILINEAR),
        (1.0, 2.0, RasterPresentationSampling.NEAREST),
        (0.5, 3.0, RasterPresentationSampling.BILINEAR),
    ),
)
def test_sampling_policy_switches_at_two_physical_pixels_per_source_pixel(
    logical_scale: float,
    device_pixel_ratio: float,
    expected: RasterPresentationSampling,
) -> None:
    """Every rasterized layer should share one physical-pixel sharpness threshold."""
    transform = QTransform()
    transform.scale(logical_scale, logical_scale)

    assert raster_presentation_sampling(transform, device_pixel_ratio) is expected


@pytest.mark.parametrize("device_pixel_ratio", (1.0, 1.5, 2.0, 3.0))
def test_source_native_threshold_does_not_move_with_display_density(
    device_pixel_ratio: float,
) -> None:
    """The base-image 200% boundary stays relative to its real-pixel 1:1 zoom."""
    assert (
        raster_presentation_sampling_for_source_scale(1.999)
        is RasterPresentationSampling.BILINEAR
    )
    assert (
        exact_raster_sampling(
            QTransform.fromScale(1.0 / device_pixel_ratio, 1.0 / device_pixel_ratio),
            device_pixel_ratio,
            source_native_scale=2.0,
        )
        is RasterExactSampling.NEAREST
    )


def test_exact_operation_is_named_by_mapping_and_source_native_threshold() -> None:
    """Settled sampling distinguishes Lanczos3, affine bilinear, and nearest."""
    axis = QTransform.fromScale(1.25, 1.25)
    affine = QTransform(axis)
    affine.rotate(15.0)

    assert exact_raster_sampling(axis, 1.0) is RasterExactSampling.LANCZOS3
    assert exact_raster_sampling(affine, 1.0) is RasterExactSampling.AFFINE_BILINEAR
    assert (
        exact_raster_sampling(axis, 1.0, source_native_scale=2.0)
        is RasterExactSampling.NEAREST
    )


@pytest.mark.parametrize(
    ("physical_scale", "expected"),
    (
        (1.99, None),
        (2.0, 1.0),
        (8.0, 1.0),
    ),
)
def test_native_sample_cap_only_applies_during_sharp_presentation(
    physical_scale: float,
    expected: float | None,
) -> None:
    """Filtered fractional views should retain detail until pixels turn sharp."""
    transform = QTransform.fromScale(physical_scale, physical_scale)

    assert raster_sample_scale_limit(transform, 1.0) == expected
