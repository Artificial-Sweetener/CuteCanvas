#    CuteCanvas - High-performance layered image editor
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
"""Revision-stable selected-layer and visible-scene Clone Stamp sampling."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
from qpane.sdk.raster import (
    numpy_to_qimage_argb32,
    qimage_to_numpy_argb32,
)
from qpane.sdk.rendering import SceneLayerRenderScope, SceneRegionRasterizer
from qpane.sdk.scene import (
    LayerDescriptor,
    LayerTransform,
    RasterBounds,
    SceneDescriptor,
)

from ..painting.clone_model import CloneStampMapping
from ..resources import ProjectResourceReference
from .revision_reader import RasterRevisionReader


@dataclass(frozen=True, slots=True)
class _PreStrokeRasterOverride:
    """Expose one editable asset's immutable pre-stroke revision to QPane."""

    raster_id: uuid.UUID
    source: RasterRevisionReader

    def sample(
        self,
        layer: LayerDescriptor,
        local_bounds: RasterBounds,
    ) -> QImage | None:
        """Return pre-stroke pixels for every instance of the target resource."""
        reference = layer.source
        if (
            not isinstance(reference, ProjectResourceReference)
            or reference.resource_id != self.raster_id
        ):
            return None
        return numpy_to_qimage_argb32(self.source.read(local_bounds))


class CloneSourceSampler:
    """Cache immutable destination-aligned rendered samples for one clone stroke."""

    def __init__(
        self,
        *,
        source: RasterRevisionReader,
        scene: SceneDescriptor,
        scene_rasterizer: SceneRegionRasterizer,
        resource_revision: Callable[[uuid.UUID], int | None],
        target_resource_id: uuid.UUID,
    ) -> None:
        """Bind one source revision and frozen scene without copying either."""
        self._source = source
        self._scene = scene
        self._scene_rasterizer = scene_rasterizer
        self._resource_revision = resource_revision
        self._target_resource_id = target_resource_id
        self._initial_revisions = self._capture_resource_revisions(scene)
        self._sampled_tiles: dict[RasterBounds, np.ndarray] = {}

    @property
    def source(self) -> RasterRevisionReader:
        """Return the copy-on-write reader that preserves destination overlap."""
        return self._source

    def pixels(
        self,
        layer: LayerDescriptor,
        destination: RasterBounds,
        sample_bounds: RasterBounds,
        mapping: CloneStampMapping,
    ) -> np.ndarray | None:
        """Return a destination crop from one cached canonical source tile."""
        cached = self._sampled_tiles.get(sample_bounds)
        if cached is not None:
            return _crop_sample(cached, sample_bounds, destination)
        sampled = self._rendered_scene_pixels(layer, sample_bounds, mapping)
        if sampled is not None:
            self._sampled_tiles[sample_bounds] = sampled
            return _crop_sample(sampled, sample_bounds, destination)
        return None

    def source_is_current(self, mapping: CloneStampMapping) -> bool:
        """Return whether every non-target resource in the frozen scope is unchanged."""
        scope = mapping.layer_ids
        for layer in self._scene.layers:
            if scope is not None and layer.layer_id not in scope:
                continue
            reference = layer.source
            if (
                not isinstance(reference, ProjectResourceReference)
                or reference.resource_id == self._target_resource_id
            ):
                continue
            initial = self._initial_revisions.get(reference.resource_id)
            if (
                initial is None
                or self._resource_revision(reference.resource_id) != initial
            ):
                return False
        return True

    def _rendered_scene_pixels(
        self,
        layer: LayerDescriptor,
        destination: RasterBounds,
        mapping: CloneStampMapping,
    ) -> np.ndarray | None:
        """Sample the frozen rendered source scope through destination geometry."""
        transform = layer.transform
        if transform is None:
            return None
        destination_to_source = mapping.sample_mapping.layer_raster_to_source_scene(
            transform
        )
        source_to_destination = destination_to_source.inverted()
        if source_to_destination is None:
            return None
        scene_to_pixels = source_to_destination.followed_by(
            LayerTransform(
                dx=-float(destination.x),
                dy=-float(destination.y),
            )
        ).to_qtransform()
        reference = layer.source
        if not isinstance(reference, ProjectResourceReference):
            return None
        image = self._scene_rasterizer.rasterize(
            self._scene,
            QSize(destination.width, destination.height),
            scene_to_pixels,
            layer_scope=SceneLayerRenderScope(mapping.layer_ids),
            raster_override=_PreStrokeRasterOverride(
                reference.resource_id,
                self._source,
            ),
        )
        return qimage_to_numpy_argb32(image)

    def _capture_resource_revisions(
        self,
        scene: SceneDescriptor,
    ) -> dict[uuid.UUID, int]:
        """Capture cheap revision tokens for resources represented in one scene."""
        revisions: dict[uuid.UUID, int] = {}
        for layer in scene.layers:
            reference = layer.source
            if not isinstance(reference, ProjectResourceReference):
                continue
            revision = self._resource_revision(reference.resource_id)
            if revision is not None:
                revisions[reference.resource_id] = revision
        return revisions


def _crop_sample(
    pixels: np.ndarray,
    sample_bounds: RasterBounds,
    destination: RasterBounds,
) -> np.ndarray:
    """Return destination-aligned pixels from a containing cached sample."""
    left = destination.x - sample_bounds.x
    top = destination.y - sample_bounds.y
    if (
        left < 0
        or top < 0
        or destination.right > sample_bounds.right
        or destination.bottom > sample_bounds.bottom
    ):
        raise ValueError("clone destination must lie within cached sample bounds")
    return pixels[
        top : top + destination.height,
        left : left + destination.width,
    ]
