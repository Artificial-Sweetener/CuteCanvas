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
"""Coordinate every transient raster edit through one presentation pipeline."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace

import numpy as np
from qpane.sdk.scene import (
    RasterBounds,
    RasterLayerRenderItem,
    SampledLayerRenderItem,
    SceneDescriptor,
    SceneLayerAssetKey,
    SceneRenderItem,
    TransientRasterContribution,
)

from ..masks.live_preview_raster import LiveMaskPreviewPatches
from ..masks.live_preview_store import MaskLivePreviewStore
from ..scene.layer_edge_preview import LayerEdgePreviewStore
from ..scene.pixel_fragments import RasterPixelFormat
from ..scene.pixel_move_preview import RasterPixelMovePreview
from ..scene.pixel_transitions import RasterPixelTransition
from ..scene.source_capabilities import EditorSourceCapabilities
from .floating_pixels import FloatingPixelRenderCompiler
from .layer_edge_preview import LayerEdgePreviewRenderCompiler
from .raster_transitions import RasterTransitionRenderCompiler, raster_item_asset_key


@dataclass(frozen=True, slots=True)
class _SettlingMaskPreview:
    """Retain one committed preview until this view sees a newer source revision."""

    preview: LiveMaskPreviewPatches
    previous_asset_key: SceneLayerAssetKey | None
    contribution: TransientRasterContribution | None


class MaskLivePreviewRenderCompiler:
    """Compile document-shared mask patches as exact transient transitions."""

    def __init__(
        self,
        capabilities: EditorSourceCapabilities,
        previews: MaskLivePreviewStore,
        current_scene: Callable[[], SceneDescriptor | None],
    ) -> None:
        """Bind authoritative coverage, presentation, and scene owners."""
        self._capabilities = capabilities
        self._previews = previews
        self._current_scene = current_scene
        self._observed_asset_keys: dict[uuid.UUID, SceneLayerAssetKey] = {}
        self._last_contributions: dict[uuid.UUID, TransientRasterContribution] = {}
        self._settling: dict[uuid.UUID, _SettlingMaskPreview] = {}
        self._closed = False
        self._transitions = RasterTransitionRenderCompiler(
            capabilities.pixel_presentation
        )
        previews.settlement_prepared.connect(self._capture_settlement)

    def shutdown(self) -> None:
        """Release document observation and retained settlement snapshots."""
        if self._closed:
            return
        self._closed = True
        try:
            self._previews.settlement_prepared.disconnect(self._capture_settlement)
        except RuntimeError:
            pass
        self._observed_asset_keys.clear()
        self._last_contributions.clear()
        self._settling.clear()

    def target(self) -> tuple[uuid.UUID, uuid.UUID, RasterBounds] | None:
        """Return the visible layer and local bounds carrying a mask preview."""
        scene = self._current_scene()
        if scene is None:
            return None
        for layer in scene.layers:
            resource_id = getattr(layer.source, "resource_id", None)
            if not isinstance(resource_id, uuid.UUID):
                continue
            preview = self._preview(resource_id)
            if preview is not None and preview.content_bounds is not None:
                return scene.scene_id, layer.layer_id, preview.content_bounds
        return None

    def compile(
        self,
        render_items: tuple[SceneRenderItem, ...],
    ) -> TransientRasterContribution | None:
        """Return the first exact provisional mask contribution in this scene."""
        for candidate in render_items:
            if not isinstance(
                candidate, (RasterLayerRenderItem, SampledLayerRenderItem)
            ):
                continue
            descriptor = candidate.descriptor
            resource_id = getattr(descriptor.source, "resource_id", None)
            if not isinstance(resource_id, uuid.UUID):
                continue
            preview = self._preview(resource_id)
            if preview is not None:
                self._observed_asset_keys[resource_id] = raster_item_asset_key(
                    candidate
                )
            settlement = self._settling.get(resource_id)
            retained_source_key: SceneLayerAssetKey | None = None
            settlement_uses_current_asset = False
            if (
                preview is not None
                and preview.retain_until_durable
                and settlement is not None
                and settlement.preview.session_id == preview.session_id
            ):
                previous_key = settlement.previous_asset_key
                settlement_uses_current_asset = (
                    previous_key is None
                    or raster_item_asset_key(candidate) != previous_key
                )
                if not settlement_uses_current_asset:
                    retained_source_key = previous_key
                elif settlement.contribution is not None:
                    return settlement.contribution
            surface_bounds = descriptor.raster_bounds
            patch_bounds = preview.content_bounds if preview is not None else None
            if preview is None or surface_bounds is None or patch_bounds is None:
                continue
            patch_bounds = patch_bounds.intersection(surface_bounds)
            if patch_bounds is None:
                continue
            snapshot = self._capabilities.coverage.coverage_snapshot(
                descriptor.source,
                patch_bounds,
            )
            if snapshot is None or snapshot.bounds != patch_bounds:
                continue
            before = snapshot.pixels
            after = np.array(before, copy=True, order="C")
            preview.apply_to(patch_bounds, after)
            transition = RasterPixelTransition(
                patch_bounds,
                surface_bounds,
                surface_bounds,
                before,
                after,
            )
            retain_until_durable = (
                preview.retain_until_durable and not settlement_uses_current_asset
            )
            contribution = self._transitions.compile(
                session_id=preview.session_id,
                scene_id=descriptor.scene_id,
                layer_id=descriptor.layer_id,
                pixel_format=RasterPixelFormat.COVERAGE8,
                transition=transition,
                generation=(preview.revision, retain_until_durable),
                item=candidate,
                retain_until_durable=retain_until_durable,
            )
            if contribution is None:
                return None
            if retained_source_key is not None:
                contribution = replace(
                    contribution,
                    source_asset_key=retained_source_key,
                )
            self._last_contributions[resource_id] = contribution
            return contribution
        return None

    def admit(self, contribution: TransientRasterContribution) -> None:
        """Release a settlement after QPane admits its exact handoff product."""
        for mask_id, settlement in tuple(self._settling.items()):
            if settlement.preview.session_id == contribution.session_id:
                self._settling.pop(mask_id, None)
                self._last_contributions.pop(mask_id, None)
                return

    def _preview(self, mask_id: uuid.UUID) -> LiveMaskPreviewPatches | None:
        """Return active coverage or this view's unpresented settlement snapshot."""
        active = self._previews.preview(mask_id)
        if active is not None:
            return active
        settlement = self._settling.get(mask_id)
        return None if settlement is None else settlement.preview

    def _capture_settlement(
        self,
        mask_id: object,
        preview: object,
    ) -> None:
        """Retain committed coverage until this view compiles its handoff frame."""
        if isinstance(mask_id, uuid.UUID) and isinstance(
            preview, LiveMaskPreviewPatches
        ):
            contribution = self._last_contributions.get(mask_id)
            if contribution is not None:
                contribution = replace(contribution, retain_until_durable=True)
            self._settling[mask_id] = _SettlingMaskPreview(
                preview,
                self._observed_asset_keys.get(mask_id),
                contribution,
            )


class TransientRasterRenderCoordinator:
    """Select one active raster edit while sharing exact transition rendering."""

    def __init__(
        self,
        capabilities: EditorSourceCapabilities,
        mask_previews: MaskLivePreviewStore,
        layer_edge_previews: LayerEdgePreviewStore,
        current_scene: Callable[[], SceneDescriptor | None],
    ) -> None:
        """Create the single transient-raster presentation boundary."""
        self._floating = FloatingPixelRenderCompiler(capabilities.pixel_presentation)
        self._layer_edges = LayerEdgePreviewRenderCompiler(
            capabilities.pixel_presentation,
            layer_edge_previews,
        )
        self._masks = MaskLivePreviewRenderCompiler(
            capabilities,
            mask_previews,
            current_scene,
        )

    def shutdown(self) -> None:
        """Release view-scoped transient presentation observation."""
        self._masks.shutdown()

    def admit(self, contribution: TransientRasterContribution) -> None:
        """Acknowledge one contribution after QPane admits it for painting."""
        self._masks.admit(contribution)

    def target(
        self,
        pixel_preview: RasterPixelMovePreview | None,
    ) -> tuple[uuid.UUID, uuid.UUID, RasterBounds] | None:
        """Return the active transient target and its local support bounds."""
        pixel_target = self._floating.target(pixel_preview)
        if pixel_target is not None:
            return pixel_target
        layer_edge_target = self._layer_edges.target()
        return (
            layer_edge_target if layer_edge_target is not None else self._masks.target()
        )

    def compile(
        self,
        pixel_preview: RasterPixelMovePreview | None,
        render_items: tuple[SceneRenderItem, ...],
    ) -> TransientRasterContribution | None:
        """Compile the active pixel move or the shared mask preview."""
        pixel_contribution = self._floating.compile(pixel_preview, render_items)
        if pixel_contribution is not None:
            return pixel_contribution
        layer_edge_contribution = self._layer_edges.compile(render_items)
        if layer_edge_contribution is not None:
            return layer_edge_contribution
        return self._masks.compile(render_items)


__all__ = ["MaskLivePreviewRenderCompiler", "TransientRasterRenderCoordinator"]
