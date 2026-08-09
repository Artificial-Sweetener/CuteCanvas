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

"""Contracts for current-geometry fallback from prior sampled products."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QRect
from PySide6.QtGui import QTransform
from qpane.rendering.sampled_projection_fallback import (
    reproject_sampled_fallback,
)
from qpane.scene.affine import LayerTransform
from qpane.scene.render_plan import SampledLayerRenderItem
from qpane_test_support.render_plan import make_render_plan


def test_source_compatible_samples_are_reprojected_under_current_geometry() -> None:
    """Spatial refinement retains pixels without restoring an obsolete mapping."""
    plan = make_render_plan(QRect(0, 0, 32, 32))
    raster = plan.render_items[0]
    prior = SampledLayerRenderItem(
        descriptor=raster.descriptor,
        transform=QTransform(),
        placement=raster.descriptor.placement,
        clip=raster.descriptor.clip,
        source_size=raster.source_image.size(),
        render_hint_enabled=False,
        tiles=(),
    )
    current_transform = QTransform.fromTranslate(18.0, -7.0)

    current_descriptor = replace(
        prior.descriptor,
        transform=LayerTransform(dx=18.0, dy=-7.0),
    )
    fallback = reproject_sampled_fallback(
        {prior.descriptor.layer_id: prior},
        descriptor=current_descriptor,
        transform=current_transform,
        source_size=prior.source_size,
        render_hint_enabled=True,
    )

    assert fallback is not None
    assert fallback.descriptor is current_descriptor
    assert fallback.transform == current_transform
    assert fallback.tiles is prior.tiles
    assert fallback.render_hint_enabled


def test_viewport_only_projection_change_does_not_create_layer_fallback() -> None:
    """Navigation leaves continuity to the dedicated viewport reuse path."""
    plan = make_render_plan(QRect(0, 0, 32, 32))
    raster = plan.render_items[0]
    prior = SampledLayerRenderItem(
        descriptor=raster.descriptor,
        transform=QTransform(),
        placement=raster.descriptor.placement,
        clip=raster.descriptor.clip,
        source_size=raster.source_image.size(),
        render_hint_enabled=False,
        tiles=(),
    )

    fallback = reproject_sampled_fallback(
        {prior.descriptor.layer_id: prior},
        descriptor=prior.descriptor,
        transform=QTransform.fromScale(5.0, 5.0),
        source_size=prior.source_size,
        render_hint_enabled=True,
    )

    assert fallback is None


def test_changed_source_revision_rejects_prior_sampled_pixels() -> None:
    """Content transitions never relabel stale pixels as a current source product."""
    plan = make_render_plan(QRect(0, 0, 32, 32))
    raster = plan.render_items[0]
    prior = SampledLayerRenderItem(
        descriptor=raster.descriptor,
        transform=QTransform(),
        placement=raster.descriptor.placement,
        clip=raster.descriptor.clip,
        source_size=raster.source_image.size(),
        render_hint_enabled=False,
        tiles=(),
    )

    fallback = reproject_sampled_fallback(
        {prior.descriptor.layer_id: prior},
        descriptor=replace(
            prior.descriptor,
            source_revision=prior.descriptor.source_revision + 1,
        ),
        transform=QTransform(),
        source_size=prior.source_size,
        render_hint_enabled=False,
    )

    assert fallback is None
