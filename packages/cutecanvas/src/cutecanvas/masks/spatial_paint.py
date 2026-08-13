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
from dataclasses import dataclass

from PySide6.QtCore import QRect

from qpane.sdk.execution import ExecutionScope
from qpane.sdk.scene import (
    BilinearLayerTransform,
    LayerDescriptor,
    LayerTransform,
    PiecewiseLayerTransform,
)

from ..composition.geometry_policy import LayerGeometryMode, LayerGeometryPolicy
from ..composition.layers import CompositionLayerInstance
from ..coverage import CoverageAsset
from ..resources import ProjectResourceReference
from .coverage_history import MaskCoverageState
from .layer_coordination import MaskLayerCoordinator
from .mask import MaskAssetStore, MaskLayer
from .mask_controller import MaskController
from .paint_preparation import MaskPaintPreparationCache
from .projection import project_mask_coverage_to_scene
from .spatial_paint_history import (
    MaskInstanceMappingTransition,
    MaskSpatialPaintHistory,
    MaskSpatialPaintTransition,
)
from .spatial_paint_layers import update_spatial_paint_geometry


@dataclass(frozen=True, slots=True)
class _SpatialPaintProjectionKey:
    """Identify exact mask pixels and instance geometry prepared for painting."""

    mask_id: uuid.UUID
    composition_id: uuid.UUID
    layer_id: uuid.UUID
    coverage_revision: tuple[int, int]
    transform: BilinearLayerTransform | PiecewiseLayerTransform


@dataclass(frozen=True, slots=True)
class _SpatialPaintTarget:
    """Carry one validated finite instance and its immutable projection inputs."""

    mask_id: uuid.UUID
    composition_id: uuid.UUID
    asset: MaskLayer
    instance: CompositionLayerInstance
    key: _SpatialPaintProjectionKey


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
        execution_scope: ExecutionScope,
    ) -> None:
        """Bind mask authority, instance geometry, and publication owners."""
        self._assets = assets
        self._layers = layers
        self._controller = controller
        self._history = history
        self._current_composition_id = current_composition_id
        self._projections = MaskPaintPreparationCache(
            execution_scope,
            owner="mask-spatial-paint",
        )

    def warm(self, layer: LayerDescriptor) -> bool:
        """Prepare an exact finite-mapping projection away from the GUI thread."""
        if not isinstance(
            layer.transform,
            (BilinearLayerTransform, PiecewiseLayerTransform),
        ):
            return True
        target = self._target(layer)
        if target is None:
            return False
        state = target.asset.coverage.state_snapshot()
        transform = target.key.transform
        mask_id = target.mask_id
        return self._projections.warm(
            target.key,
            lambda: project_mask_coverage_to_scene(
                CoverageAsset.from_snapshot(
                    mask_id,
                    state,
                ).snapshot(),
                transform,
            ),
        )

    def ready(self, layer: LayerDescriptor) -> bool:
        """Return whether the exact finite target has a prepared projection."""
        if not isinstance(
            layer.transform,
            (BilinearLayerTransform, PiecewiseLayerTransform),
        ):
            return True
        target = self._target(layer)
        return target is not None and self._projections.is_ready(target.key)

    def shutdown(self) -> None:
        """Cancel pending spatial preparation during editor teardown."""
        self._projections.shutdown()

    def prepare(self, layer: LayerDescriptor) -> bool:
        """Replace a finite mapping with equivalent scene-space mask coverage."""
        if not isinstance(
            layer.transform,
            (BilinearLayerTransform, PiecewiseLayerTransform),
        ):
            return True
        target = self._target(layer)
        if target is None:
            return False
        transform = target.key.transform
        before = _coverage_state(target.asset)
        projected = self._projections.product(target.key)
        if projected is None:
            projected = project_mask_coverage_to_scene(
                target.asset.coverage.snapshot(),
                transform,
            )
        self._projections.discard()
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
            target.composition_id,
            layer.layer_id,
            LayerTransform(),
            normalized_geometry,
        ):
            return False
        if not self._assets.coverage_edits.replace_spatial_authority(
            target.mask_id,
            projected,
        ):
            update_spatial_paint_geometry(
                self._layers.store,
                target.composition_id,
                layer.layer_id,
                transform,
                target.instance.geometry,
            )
            return False
        self._history.capture(
            MaskSpatialPaintTransition(
                target.mask_id,
                before,
                _coverage_state(target.asset),
                (
                    MaskInstanceMappingTransition(
                        target.composition_id,
                        layer.layer_id,
                        transform,
                        LayerTransform(),
                        target.instance.geometry,
                        normalized_geometry,
                    ),
                ),
            )
        )
        self._controller.edits.advance_epoch(
            target.mask_id,
            reason="spatial_paint_normalization",
        )
        self._controller.renders.invalidate(
            target.mask_id,
            reason="spatial_paint_normalization",
        )
        self._controller.mask_updated.emit(target.mask_id, QRect())
        return True

    def _target(self, layer: LayerDescriptor) -> _SpatialPaintTarget | None:
        """Resolve one uniquely owned finite mask instance and immutable key."""
        transform = layer.transform
        source = layer.source
        if not isinstance(
            transform,
            (BilinearLayerTransform, PiecewiseLayerTransform),
        ):
            return None
        if not isinstance(source, ProjectResourceReference):
            return None
        mask_id = source.resource_id
        asset = self._assets.get_layer(mask_id)
        composition_id = self._current_composition_id()
        if asset is None or composition_id is None:
            return None
        instance = self._layers.store.layer(composition_id, layer.layer_id)
        if (
            instance is None
            or instance.source != source
            or instance.transform != transform
        ):
            return None
        composition_ids = self._layers.composition_ids_for_mask(mask_id)
        source_instances = tuple(
            candidate
            for owner_id in composition_ids
            for candidate in self._layers.instances_for_composition(owner_id)
            if candidate.source == source
        )
        if composition_ids != (composition_id,) or len(source_instances) != 1:
            return None
        return _SpatialPaintTarget(
            mask_id,
            composition_id,
            asset,
            instance,
            _SpatialPaintProjectionKey(
                mask_id,
                composition_id,
                layer.layer_id,
                asset.coverage.revision,
                transform,
            ),
        )


def _coverage_state(asset: MaskLayer) -> MaskCoverageState:
    """Capture one detached hybrid revision from a validated mask asset."""
    coverage = asset.coverage
    return MaskCoverageState(
        coverage.raster.state_snapshot(),
        coverage.retained,
    )


__all__ = ["MaskSpatialPaintNormalizer"]
