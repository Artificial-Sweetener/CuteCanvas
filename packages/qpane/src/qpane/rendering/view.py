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

"""Compose rendering, catalog, link, and swap collaborators behind QPane.view()."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Protocol

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize
from PySide6.QtGui import QTransform

from ..cache.registry import CacheRegistry
from ..catalog import CatalogController, ImageCatalog, LinkManager
from ..catalog.scene_resolver import CatalogSceneResolver
from ..core import (
    CacheSettings,
    Config,
    PrefetchSettings,
)
from ..scene.effects import LayerEffectRenderRegistry
from ..scene.identity import SceneLayerTileKey
from ..scene.presentation_effects import (
    LayerPresentationEffect,
    LayerPresentationStyle,
)
from ..scene.registry import SceneProviderRegistry
from ..scene.source_capabilities import LayerSourceCapabilities
from ..scene.source_references import PlaceholderImageReference
from ..swap import SwapDelegate
from ..swap.diagnostics import swap_progress_provider, swap_summary_provider
from .coordinates import PanelHitTest
from .diagnostics import rendering_retry_provider
from .placeholder_source import PlaceholderSourceCapabilities
from .presenter import RenderingPresenter

if TYPE_CHECKING:  # pragma: no cover - import guard for typing only

    from ..concurrency import TaskExecutorProtocol
    from ..core.diagnostics_broker import Diagnostics
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
    """Minimal state contract required by the catalog-backed viewer surface."""

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
        catalog: ImageCatalog,
        pyramid_manager: PyramidManager,
        executor: TaskExecutorProtocol,
        scene_providers: SceneProviderRegistry,
        source_capabilities: LayerSourceCapabilities,
        layer_effects: LayerEffectRenderRegistry,
    ) -> None:
        """Wire rendering/swap/catalog collaborators owned by QPane.view()."""
        self._qpane = qpane
        self._state = state
        self._catalog = catalog
        self._pyramid_manager = pyramid_manager
        self._executor = executor
        self._cache_registry: CacheRegistry | None = state.cache_registry
        self._placeholder_source = PlaceholderSourceCapabilities()
        self._scene_resolver = CatalogSceneResolver(catalog, scene_providers)
        source_capabilities.metadata.register(
            PlaceholderImageReference, self._placeholder_source
        )
        source_capabilities.rasters.register(
            PlaceholderImageReference, self._placeholder_source
        )
        source_capabilities.hit_tests.register(
            PlaceholderImageReference, self._placeholder_source
        )
        self._attach_pyramid_manager()
        self.presenter = RenderingPresenter(
            qpane=qpane,
            pyramid_products=pyramid_manager,
            cache_registry=self._cache_registry,
            executor=executor,
            scene_provider=self._scene_resolver.scene,
            scene_revision=self._scene_resolver.revision,
            source_metadata=source_capabilities.metadata,
            raster_sources=source_capabilities.rasters,
            raster_patches=source_capabilities.raster_patches,
            source_hit_tests=source_capabilities.hit_tests,
            vector_sources=source_capabilities.vectors,
            hybrid_sources=source_capabilities.hybrids,
            layer_effects=layer_effects,
        )
        qpane.destroyed.connect(
            lambda _obj=None, presenter=self.presenter: presenter.shutdown()
        )
        self.viewport = self.presenter.viewport
        self.tile_manager = self.presenter.tile_manager
        self.renderer = self.presenter.renderer
        self.link_manager = LinkManager()
        self.swap_delegate = SwapDelegate(
            qpane=qpane,
            catalog=catalog,
            viewport=self.viewport,
            tile_manager=self.tile_manager,
            pyramid_manager=pyramid_manager,
            rendering=self.presenter,
            prefetch_settings=self._prefetch_settings_from_config(qpane.settings),
            mark_dirty=self.mark_dirty,
        )
        self.catalog_controller = CatalogController(
            qpane=qpane,
            catalog=catalog,
            viewport=self.viewport,
            tile_manager=self.tile_manager,
            link_manager=self.link_manager,
            swap_delegate=self.swap_delegate,
        )
        self._scene_resolver.set_placeholder_provider(
            self.catalog_controller.placeholder_content
        )
        self._placeholder_source.set_provider(
            self.catalog_controller.placeholder_content
        )
        self.swap_delegate.attach_catalog_controller(self.catalog_controller)
        self._connect_rendering_signals()

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

    def ensure_view_alignment(self, *, force: bool = False) -> None:
        """Keep the viewport aligned via the presenter helper."""
        self.presenter.ensure_view_alignment(force=force)

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
        transform = self.scene_to_panel_transform()
        return None if transform is None else transform.map(QPointF(scene_point))

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
        """Install rendering and swap diagnostics providers via the diagnostics manager."""
        broker.register_swap_providers(swap_summary_provider, tier="core")
        broker.register_swap_providers(swap_progress_provider)
        broker.register_provider(
            rendering_retry_provider,
            domain="retry",
            tier="detail",
        )

    def handle_tile_ready(self, key: SceneLayerTileKey) -> None:
        """Forward tile-ready signals to the swap delegate."""
        self.swap_delegate.handle_tile_ready(key)

    def handle_pyramid_ready(self, asset_key: object | None) -> None:
        """Bridge pyramid-ready notifications from the catalog to swap plumbing."""
        self.swap_delegate.handle_pyramid_ready(asset_key)

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

    def _prefetch_settings_from_config(self, config: Config) -> PrefetchSettings:
        """Return a PrefetchSettings clone from config.cache, enforcing the expected shape."""
        cache_settings = getattr(config, "cache", None)
        if not isinstance(cache_settings, CacheSettings):
            raise TypeError("config.cache must be a CacheSettings instance")
        prefetch = cache_settings.prefetch
        if not isinstance(prefetch, PrefetchSettings):
            raise TypeError("config.cache.prefetch must be a PrefetchSettings instance")
        return prefetch.clone()
