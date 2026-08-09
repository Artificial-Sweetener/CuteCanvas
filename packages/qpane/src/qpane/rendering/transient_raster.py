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

from dataclasses import dataclass, replace

from PySide6.QtCore import QRectF

from ..scene.identity import SceneLayerAssetKey
from ..scene.render_plan import (
    RasterLayerRenderItem,
    SampledLayerRenderItem,
    SampledTileRenderData,
    SceneRenderPlan,
    TransientRasterContribution,
    TransientRasterResolvedContribution,
    TransientRasterTransformContribution,
    TransientSampledResolvedContribution,
)
from .panel_mapping import PanelMappingKey, panel_mapping_key
from .rectangle_coverage import rectangles_cover


@dataclass(frozen=True, slots=True)
class _SampledViewKey:
    """Identify presentation geometry that can reuse one sampled contribution."""

    zoom: float
    pan: tuple[float, float]
    viewport: tuple[float, float, float, float]
    item_transform: PanelMappingKey

    @classmethod
    def from_plan(
        cls,
        plan: SceneRenderPlan,
        item: SampledLayerRenderItem,
    ) -> _SampledViewKey:
        """Return exact view and layer geometry for one sampled presentation."""
        viewport = plan.physical_viewport_rect
        return cls(
            zoom=plan.zoom,
            pan=(plan.current_pan.x(), plan.current_pan.y()),
            viewport=(
                viewport.x(),
                viewport.y(),
                viewport.width(),
                viewport.height(),
            ),
            item_transform=panel_mapping_key(item.transform),
        )


class TransientRasterHandoff:
    """Keep a generic transient raster visible until its durable revision appears."""

    def __init__(self) -> None:
        """Initialize without a contribution awaiting durable presentation."""
        self._pending: TransientRasterContribution | None = None
        self._durable_asset_key: SceneLayerAssetKey | None = None
        self._sampled_view_key: _SampledViewKey | None = None

    def settled_plan(self, plan: SceneRenderPlan) -> tuple[SceneRenderPlan, bool]:
        """Return a plan that cannot flash before a newer durable revision arrives."""
        active = plan.transient_raster
        if active is not None:
            item = self._matching_item(plan, active)
            if isinstance(active, TransientSampledResolvedContribution):
                if not isinstance(
                    item, SampledLayerRenderItem
                ) or not _sampled_contribution_covers(item, active):
                    self._clear()
                    return replace(plan, transient_raster=None), True
                self._sampled_view_key = _SampledViewKey.from_plan(plan, item)
            elif isinstance(
                active,
                TransientRasterResolvedContribution,
            ) and isinstance(item, SampledLayerRenderItem):
                self._sampled_view_key = _SampledViewKey.from_plan(plan, item)
            else:
                self._sampled_view_key = None
            self._pending = active
            self._durable_asset_key = None
            return plan, False
        pending = self._pending
        if pending is None:
            return plan, False
        if not getattr(pending, "retain_until_durable", True):
            self._clear()
            return plan, True
        if isinstance(pending, TransientRasterTransformContribution):
            self._clear()
            return plan, True
        item = self._matching_item(plan, pending)
        if isinstance(pending, TransientSampledResolvedContribution):
            return self._settled_sampled_plan(plan, item, pending)
        if isinstance(
            pending,
            TransientRasterResolvedContribution,
        ) and isinstance(item, SampledLayerRenderItem):
            return self._settled_sampled_patch_plan(plan, item, pending)
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
        if (
            (
                pending.sampled_raster_bounds is not None
                and item.descriptor.raster_bounds != pending.sampled_raster_bounds
            )
            or (
                pending.sampled_source_size is not None
                and item.source_size != pending.sampled_source_size
            )
            or not _sampled_contribution_covers(item, pending)
            or self._sampled_view_key != _SampledViewKey.from_plan(plan, item)
        ):
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
        if self._durable_asset_key is None:
            self._durable_asset_key = asset_key
        elif asset_key != self._durable_asset_key:
            self._clear()
            return plan, True
        return replace(plan, transient_raster=pending), False

    def _settled_sampled_patch_plan(
        self,
        plan: SceneRenderPlan,
        item: SampledLayerRenderItem,
        pending: TransientRasterResolvedContribution,
    ) -> tuple[SceneRenderPlan, bool]:
        """Retain one bounded patch without replacing unrelated sampled tiles."""
        if self._sampled_view_key != _SampledViewKey.from_plan(plan, item):
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
        if self._durable_asset_key is None:
            self._durable_asset_key = asset_key
        elif asset_key != self._durable_asset_key:
            self._clear()
            return plan, True
        return replace(plan, transient_raster=pending), False

    @staticmethod
    def _matching_item(
        plan: SceneRenderPlan,
        pending: TransientRasterContribution,
    ) -> object:
        """Return the current render item targeted by one contribution."""
        return next(
            (
                candidate
                for candidate in plan.render_items
                if candidate.descriptor.scene_id == pending.scene_id
                and candidate.descriptor.layer_id == pending.layer_id
            ),
            None,
        )

    def _clear(self) -> None:
        """Release retained transient products and revision identity."""
        self._pending = None
        self._durable_asset_key = None
        self._sampled_view_key = None


def _sampled_contribution_covers(
    item: SampledLayerRenderItem,
    contribution: TransientSampledResolvedContribution,
) -> bool:
    """Return whether current products cover the retained presentation demand."""
    if (
        contribution.sampled_raster_bounds is not None
        and item.descriptor.raster_bounds != contribution.sampled_raster_bounds
    ) or (
        contribution.sampled_source_size is not None
        and item.source_size != contribution.sampled_source_size
    ):
        return False
    current = tuple(_painted_source_rect(tile) for tile in item.tiles)
    retained = tuple(_painted_source_rect(tile) for tile in contribution.tiles)
    return all(rectangles_cover(rect, current) for rect in retained)


def _painted_source_rect(tile: SampledTileRenderData) -> QRectF:
    """Return the source-local core actually painted for one sampled tile."""
    return tile.source_clip_rect or tile.source_rect
