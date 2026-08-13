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

"""Reproject source-compatible sampled products during spatial refinement."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import replace

from PySide6.QtCore import QSize

from ..scene.model import LayerDescriptor
from ..scene.raster_sampling import RasterPresentationSampling
from ..scene.render_plan import SampledLayerRenderItem
from .panel_mapping import PanelLayerMapping


def reproject_sampled_fallback(
    prior_items: Mapping[uuid.UUID, SampledLayerRenderItem],
    *,
    descriptor: LayerDescriptor,
    transform: PanelLayerMapping,
    source_size: QSize,
    presentation_sampling: RasterPresentationSampling,
) -> SampledLayerRenderItem | None:
    """Reuse prior samples under current geometry when source pixels are unchanged."""
    prior = prior_items.get(descriptor.layer_id)
    if (
        prior is None
        or not _source_matches(prior, descriptor, source_size)
        or not _geometry_changed(prior.descriptor, descriptor)
    ):
        return None
    return replace(
        prior,
        descriptor=descriptor,
        transform=transform,
        placement=descriptor.placement,
        clip=descriptor.clip,
        source_size=QSize(source_size),
        presentation_sampling=presentation_sampling,
        mapping_clip_path=None,
        effect_clip_path=None,
    )


def _geometry_changed(previous: LayerDescriptor, current: LayerDescriptor) -> bool:
    """Return whether the layer itself needs current-geometry reprojection."""
    return (
        previous.placement != current.placement
        or previous.transform != current.transform
        or previous.clip != current.clip
    )


def _source_matches(
    prior: SampledLayerRenderItem,
    descriptor: LayerDescriptor,
    source_size: QSize,
) -> bool:
    """Return whether prior pixels represent the exact current source revision."""
    previous = prior.descriptor
    return (
        previous.source == descriptor.source
        and previous.source_revision == descriptor.source_revision
        and previous.raster_bounds == descriptor.raster_bounds
        and prior.source_size == source_size
    )


__all__ = ["reproject_sampled_fallback"]
