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
"""Preserve transient raster contributions until durable rendering catches up."""

from __future__ import annotations

from dataclasses import replace

from ..scene.identity import SceneLayerAssetKey
from ..scene.render_plan import (
    RasterLayerRenderItem,
    SampledLayerRenderItem,
    SceneRenderPlan,
    TransientRasterContribution,
    TransientRasterTransformContribution,
    TransientSampledResolvedContribution,
)


class TransientRasterHandoff:
    """Keep a generic transient raster visible until its durable revision appears."""

    def __init__(self) -> None:
        """Initialize without a contribution awaiting durable presentation."""
        self._pending: TransientRasterContribution | None = None
        self._durable_asset_key: SceneLayerAssetKey | None = None

    def settled_plan(self, plan: SceneRenderPlan) -> tuple[SceneRenderPlan, bool]:
        """Return a plan that cannot flash before a newer durable revision arrives."""
        if plan.transient_raster is not None:
            self._pending = plan.transient_raster
            self._durable_asset_key = None
            return plan, False
        pending = self._pending
        if pending is None:
            return plan, False
        if isinstance(pending, TransientRasterTransformContribution):
            self._clear()
            return plan, True
        item = next(
            (
                candidate
                for candidate in plan.render_items
                if candidate.descriptor.scene_id == pending.scene_id
                and candidate.descriptor.layer_id == pending.layer_id
            ),
            None,
        )
        if isinstance(pending, TransientSampledResolvedContribution):
            return self._settled_sampled_plan(plan, item, pending)
        if not isinstance(item, RasterLayerRenderItem):
            self._clear()
            return plan, True
        if item.asset_key == pending.source_asset_key:
            return replace(plan, transient_raster=pending), False
        if self._durable_asset_key is None:
            self._durable_asset_key = item.asset_key
        elif item.asset_key != self._durable_asset_key:
            self._clear()
            return plan, True
        if item.source_image == pending.source_image:
            self._clear()
            return plan, True
        return replace(plan, transient_raster=pending), False

    def _settled_sampled_plan(
        self,
        plan: SceneRenderPlan,
        item: object,
        pending: TransientSampledResolvedContribution,
    ) -> tuple[SceneRenderPlan, bool]:
        """Keep sampled edit tiles visible until matching durable tiles arrive."""
        if not isinstance(item, SampledLayerRenderItem):
            self._clear()
            return plan, True
        descriptor = item.descriptor
        asset_key = SceneLayerAssetKey(
            scene_id=descriptor.scene_id,
            layer_id=descriptor.layer_id,
            source_id=descriptor.source.resource_id,
            source_kind=descriptor.source.kind,
            source_revision=descriptor.source_revision,
        )
        if asset_key == pending.source_asset_key:
            return replace(plan, transient_raster=pending), False
        if item.tiles == pending.tiles:
            self._clear()
            return plan, False
        if self._durable_asset_key is None:
            self._durable_asset_key = asset_key
        elif asset_key != self._durable_asset_key:
            self._clear()
            return plan, True
        return replace(plan, transient_raster=pending), False

    def _clear(self) -> None:
        """Release retained transient products and revision identity."""
        self._pending = None
        self._durable_asset_key = None
