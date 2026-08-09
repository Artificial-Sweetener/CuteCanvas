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

"""Normalize finite mask mappings before unbounded raster painting."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from PySide6.QtCore import QRect
from qpane.sdk.scene import (
    BilinearLayerTransform,
    LayerDescriptor,
    LayerTransform,
    PiecewiseLayerTransform,
)

from ..composition.geometry_policy import LayerGeometryMode, LayerGeometryPolicy
from ..resources import ProjectResourceReference
from .coverage_history import MaskCoverageState
from .layer_coordination import MaskLayerCoordinator
from .mask import MaskAssetStore, MaskLayer
from .mask_controller import MaskController
from .projection import project_mask_coverage_to_scene
from .spatial_paint_history import (
    MaskInstanceMappingTransition,
    MaskSpatialPaintHistory,
    MaskSpatialPaintTransition,
)
from .spatial_paint_layers import update_spatial_paint_geometry


class MaskSpatialPaintNormalizer:
    """Bake finite instance geometry once so mask painting remains unbounded."""

    def __init__(
        self,
        *,
        assets: MaskAssetStore,
        layers: MaskLayerCoordinator,
        controller: MaskController,
        history: MaskSpatialPaintHistory,
        current_composition_id: Callable[[], uuid.UUID | None],
    ) -> None:
        """Bind mask authority, instance geometry, and publication owners."""
        self._assets = assets
        self._layers = layers
        self._controller = controller
        self._history = history
        self._current_composition_id = current_composition_id

    def prepare(self, layer: LayerDescriptor) -> bool:
        """Replace a finite mapping with equivalent scene-space mask coverage."""
        transform = layer.transform
        source = layer.source
        if not isinstance(
            transform,
            (BilinearLayerTransform, PiecewiseLayerTransform),
        ):
            return True
        if not isinstance(source, ProjectResourceReference):
            return False
        mask_id = source.resource_id
        asset = self._assets.get_layer(mask_id)
        composition_id = self._current_composition_id()
        if asset is None or composition_id is None:
            return False
        instance = self._layers.store.layer(composition_id, layer.layer_id)
        if (
            instance is None
            or instance.source != source
            or instance.transform != transform
        ):
            return False
        composition_ids = self._layers.composition_ids_for_mask(mask_id)
        source_instances = tuple(
            candidate
            for candidate_composition_id in composition_ids
            for candidate in self._layers.instances_for_composition(
                candidate_composition_id
            )
            if candidate.source == source
        )
        if composition_ids != (composition_id,) or len(source_instances) != 1:
            return False
        before = _coverage_state(asset)
        projected = project_mask_coverage_to_scene(
            asset.coverage.snapshot(),
            transform,
        )
        if projected is None:
            return False
        normalized_geometry = LayerGeometryPolicy(
            LayerGeometryMode.BOUNDARY,
            custom_boundary=tuple(
                (point.x(), point.y()) for point in transform.target_boundary
            ),
        )
        if not update_spatial_paint_geometry(
            self._layers.store,
            composition_id,
            layer.layer_id,
            LayerTransform(),
            normalized_geometry,
        ):
            return False
        if not self._assets.coverage_edits.replace_spatial_authority(
            mask_id,
            projected,
        ):
            update_spatial_paint_geometry(
                self._layers.store,
                composition_id,
                layer.layer_id,
                transform,
                instance.geometry,
            )
            return False
        self._history.capture(
            MaskSpatialPaintTransition(
                mask_id,
                before,
                _coverage_state(asset),
                (
                    MaskInstanceMappingTransition(
                        composition_id,
                        layer.layer_id,
                        transform,
                        LayerTransform(),
                        instance.geometry,
                        normalized_geometry,
                    ),
                ),
            )
        )
        self._controller.edits.advance_epoch(
            mask_id,
            reason="spatial_paint_normalization",
        )
        self._controller.renders.invalidate(
            mask_id,
            reason="spatial_paint_normalization",
        )
        self._controller.mask_updated.emit(mask_id, QRect())
        return True


def _coverage_state(asset: MaskLayer) -> MaskCoverageState:
    """Capture one detached hybrid revision from a validated mask asset."""
    coverage = asset.coverage
    return MaskCoverageState(
        coverage.raster.state_snapshot(),
        coverage.retained,
    )


__all__ = ["MaskSpatialPaintNormalizer"]
