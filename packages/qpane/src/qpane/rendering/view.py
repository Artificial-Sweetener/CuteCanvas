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

"""Coordinate one provider-driven rendering surface behind a widget facade."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Protocol

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize
from PySide6.QtGui import QTransform

from ..cache.registry import CacheRegistry
from ..scene.assembly import SceneAssembly
from ..scene.effects import LayerEffectRenderRegistry
from ..scene.identity import SceneLayerTileKey
from ..scene.presentation_effects import (
    LayerPresentationEffect,
    LayerPresentationStyle,
)
from ..scene.registry import SceneProviderRegistry
from ..scene.source_capabilities import LayerSourceCapabilities
from .coordinates import PanelHitTest
from .diagnostics import rendering_retry_provider
from .presenter import RenderingPresenter
from .scene_coordinates import SceneCoordinateSystem, ScenePoint

if TYPE_CHECKING:  # pragma: no cover - import guard for typing only

    from ..core import Config
    from ..core.diagnostics_broker import Diagnostics
    from ..execution import ExecutionScope
    from ..rendering import Renderer
    from ..scene.model import SceneDescriptor
    from ..scene.render_plan import (
        SceneContentSnapshot,
        SceneLayerHitTestResult,
        SceneRenderPlan,
    )
    from ..viewer import QPane
    from .pyramid_manager import PyramidManager


class ViewerState(Protocol):
    """Minimal state contract required by the rendering surface."""

    @property
    def cache_registry(self) -> CacheRegistry | None:
        """Return the shared cache registry when cache coordination is active."""
        ...


class View:
    """Own the rendering surface collaborators while QPane serves as a thin facade."""

    def __init__(
        self,
        *,
        qpane: QPane,
        state: ViewerState,
        pyramid_manager: PyramidManager,
        execution_scope: ExecutionScope,
        scene_providers: SceneProviderRegistry,
        source_capabilities: LayerSourceCapabilities,
        layer_effects: LayerEffectRenderRegistry,
    ) -> None:
        """Wire one provider-driven scene into the shared rendering pipeline."""
        self._qpane = qpane
        self._state = state
        self._pyramid_manager = pyramid_manager
        self._execution_scope = execution_scope.open_child(
            f"{execution_scope.owner_id}:view"
        )
        self._cache_registry: CacheRegistry | None = state.cache_registry
        self._scene_assembly = SceneAssembly(scene_providers)
        self._attach_pyramid_manager()
        self.presenter = RenderingPresenter(
            qpane=qpane,
            pyramid_products=pyramid_manager,
            cache_registry=self._cache_registry,
            execution_scope=self._execution_scope,
            scene_provider=self._scene_assembly.resolve_scene,
            scene_revision=scene_providers.revision,
            source_metadata=source_capabilities.metadata,
            raster_sources=source_capabilities.rasters,
            raster_patches=source_capabilities.raster_patches,
            source_hit_tests=source_capabilities.hit_tests,
            vector_sources=source_capabilities.vectors,
            hybrid_sources=source_capabilities.hybrids,
            sampled_sources=source_capabilities.sampled,
            layer_effects=layer_effects,
        )
        self.coordinates: SceneCoordinateSystem = self.presenter.coordinates
        self.viewport = self.presenter.viewport
        self.tile_manager = self.presenter.tile_manager
        self.renderer = self.presenter.renderer
        self._connect_rendering_signals()

    @property
    def pyramid_manager(self) -> PyramidManager:
        """Return the pyramid owner shared by every source rendered in this view."""
        return self._pyramid_manager

    def replace_renderer(self, renderer: Renderer) -> None:
        """Replace the renderer while keeping presenter and view references in sync."""
        self.presenter.renderer = renderer
        self.renderer = renderer

    def calculateRenderPlan(
        self,
        *,
        use_pan: QPointF | None = None,
        is_blank: bool = False,
    ) -> SceneRenderPlan | None:
        """Delegate scene render-plan calculation to the presenter."""
        return self.presenter.calculateRenderPlan(use_pan=use_pan, is_blank=is_blank)

    def current_content_snapshot(self) -> SceneContentSnapshot | None:
        """Expose the current rendered content geometry."""
        return self.presenter.current_content_snapshot()

    def current_scene_descriptor(self) -> SceneDescriptor | None:
        """Expose the active scene descriptor for internal mutation validation."""
        return self.presenter.current_scene_descriptor()

    def coordinate_scene_descriptor(self) -> SceneDescriptor | None:
        """Expose stable active-scene geometry for one input frame."""
        return self.presenter.coordinate_scene_descriptor()

    def invalidate_content_cache(self) -> None:
        """Drop cached scene/content geometry in the presenter."""
        self.presenter.invalidate_content_cache()

    def has_renderable_content(self) -> bool:
        """Return True when rendering can resolve scene content."""
        return self.presenter.has_renderable_content()

    def content_rect(self) -> QRect:
        """Return the base content rectangle in content coordinates."""
        return self.presenter.content_rect()

    def mark_dirty(self, dirty_rect: QRect | QRectF | None = None) -> None:
        """Forward dirty-region tracking to the presenter."""
        self.presenter.mark_dirty(dirty_rect)

    def add_layer_presentation_effect(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        style: LayerPresentationStyle,
        *,
        effect_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        """Register one transient effect against an active rendered layer."""
        return self.presenter.add_layer_presentation_effect(
            scene_id,
            layer_id,
            style,
            effect_id=effect_id,
        )

    def update_layer_presentation_effect(
        self,
        effect_id: uuid.UUID,
        style: LayerPresentationStyle,
    ) -> bool:
        """Replace one registered effect style while preserving its order."""
        return self.presenter.update_layer_presentation_effect(effect_id, style)

    def remove_layer_presentation_effect(self, effect_id: uuid.UUID) -> bool:
        """Remove one registered transient effect when present."""
        return self.presenter.remove_layer_presentation_effect(effect_id)

    def clear_layer_presentation_effects(
        self,
        *,
        scene_id: uuid.UUID | None = None,
        layer_id: uuid.UUID | None = None,
    ) -> int:
        """Remove matching transient effects and return the removal count."""
        return self.presenter.clear_layer_presentation_effects(
            scene_id=scene_id,
            layer_id=layer_id,
        )

    def layer_presentation_effects(self) -> tuple[LayerPresentationEffect, ...]:
        """Return every registered transient effect in deterministic order."""
        return self.presenter.layer_presentation_effects()

    def handle_viewport_changed(self) -> bool:
        """Let rendering handle a viewport change when a fast path is available."""
        return self.presenter.handle_viewport_changed()

    def prioritize_interaction(self) -> None:
        """Yield derived rendering work to latency-sensitive host interaction."""
        self.presenter.begin_navigation_interaction()
        self.renderer.cancel_navigation_refinement()
        self.presenter.finish_navigation_interaction()

    def ensure_view_alignment(self, *, force: bool = False) -> None:
        """Keep the viewport aligned via the presenter helper."""
        self.presenter.ensure_view_alignment(force=force)

    def apply_config(self, config: Config) -> None:
        """Apply viewport and adaptive tile-grid settings through their owners."""
        self.presenter.apply_config(config)

    def allocate_buffers(self) -> None:
        """Ask the presenter to allocate renderer buffers."""
        self.presenter.allocate_buffers()

    def physical_viewport_rect(self) -> QRectF:
        """Return the current viewport rectangle in physical pixels."""
        return self.presenter.physical_viewport_rect()

    def panel_to_image_point(self, panel_pos: QPoint) -> QPoint | None:
        """Convert panel coordinates to image coordinates via the presenter."""
        return self.presenter.panel_to_image_point(panel_pos)

    def panel_hit_test(self, panel_pos: QPoint) -> PanelHitTest | None:
        """Expose viewport hit testing for panel coordinates."""
        return self.presenter.panel_hit_test(panel_pos)

    def scene_hit_test(self, panel_pos: QPoint) -> SceneLayerHitTestResult | None:
        """Expose internal scene hit testing for panel coordinates."""
        return self.presenter.scene_hit_test(panel_pos)

    def scene_selection_hit_test(
        self, panel_pos: QPoint | QPointF
    ) -> SceneLayerHitTestResult | None:
        """Return the top selectable layer with painted source coverage."""
        return self.presenter.scene_selection_hit_test(panel_pos)

    def panel_to_scene_point(self, panel_pos: QPoint | QPointF) -> QPointF | None:
        """Project panel coordinates into active scene coordinates."""
        return self.presenter.panel_to_scene_point(panel_pos)

    def scene_to_panel_transform(self) -> QTransform | None:
        """Return the active absolute-scene to panel transform."""
        return self.presenter.scene_to_panel_transform()

    def scene_to_panel_point(self, scene_point: QPoint | QPointF) -> QPointF | None:
        """Project one absolute scene point into the panel."""
        scene = self.coordinate_scene_descriptor()
        if scene is None:
            return None
        point = self.coordinates.scene_to_panel(
            ScenePoint.from_qt(scene.scene_id, scene_point)
        )
        return None if point is None else point.to_qt()

    def panel_to_layer_source_point(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        panel_pos: QPoint | QPointF,
    ) -> QPointF | None:
        """Project panel coordinates into one layer's source space."""
        return self.presenter.panel_to_layer_source_point(
            scene_id,
            layer_id,
            panel_pos,
        )

    def layer_source_to_panel_point(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        source_point: QPoint | QPointF,
    ) -> QPointF | None:
        """Project one layer's source coordinates into panel space."""
        return self.presenter.layer_source_to_panel_point(
            scene_id,
            layer_id,
            source_point,
        )

    def image_to_panel_point(self, image_point: QPoint) -> QPointF | None:
        """Convert image coordinates to panel coordinates via the presenter."""
        return self.presenter.image_to_panel_point(image_point)

    def minimum_size_hint(self) -> QSize:
        """Expose the presenter minimum size hint."""
        return self.presenter.minimum_size_hint()

    def register_diagnostics(self, broker: Diagnostics) -> None:
        """Install rendering diagnostics through the host diagnostics manager."""
        broker.register_provider(
            rendering_retry_provider,
            domain="retry",
            tier="detail",
        )

    def handle_tile_ready(self, key: SceneLayerTileKey) -> None:
        """Invalidate the frame region completed by one derived tile."""
        if self.presenter.note_navigation_raster_tile_ready(key):
            return
        self.presenter.invalidate_frame_plan()
        dirty_rect = self.presenter.dirty_rect_for_tile_key(key)
        if dirty_rect is not None:
            self.presenter.mark_dirty(dirty_rect)
            self._qpane.update()

    def handle_pyramid_ready(self, asset_key: object | None) -> None:
        """Invalidate the frame after one source pyramid becomes available."""
        if self.presenter.note_navigation_full_product_ready():
            return
        self.presenter.invalidate_frame_plan()
        self.presenter.mark_dirty()
        self._qpane.update()

    def _attach_pyramid_manager(self) -> None:
        """Wire the rendering-owned pyramid manager into shared cache budgeting."""
        registry = self._cache_registry
        if registry is None:
            return
        registry.attach_pyramid_manager(self._pyramid_manager)

    def _connect_rendering_signals(self) -> None:
        """Connect tile/pyramid events directly to the rendering stack."""
        self.tile_manager.tileReady.connect(self.handle_tile_ready)
        self._pyramid_manager.pyramidReady.connect(self.handle_pyramid_ready)
