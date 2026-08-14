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

"""Derived-raster cache for mask scene sources."""

from __future__ import annotations

import logging
import math
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

from qpane import HybridPresentationStyle
from qpane.sdk.configuration import CacheSettings
from qpane.sdk.raster import (
    numpy_to_qimage_grayscale8,
)
from qpane.sdk.scene import RasterBounds

from ..core.config import Config
from ..core.config_features import MaskConfigSlice, require_mask_config
from .live_preview_raster import LiveMaskPreviewPatches, LiveMaskPreviewRaster
from .live_preview_store import MaskLivePreviewStore
from .mask import MaskAssetStore, MaskLayer
from .mask_undo import MaskHistoryChange
from .preview_products import preview_mask_coverage, preview_mask_overlay
from .rasterizer import MaskRasterizer
from .render_product_geometry import (
    scaled_source_rect,
    storage_damage_destination,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MaskOverlayMetrics:
    """Snapshot of mask render-cache health for diagnostics."""

    cache_bytes: int
    entry_count: int
    hits: int
    misses: int
    evictions: int
    evicted_bytes: int
    last_eviction_reason: str | None
    last_eviction_timestamp: float | None
    cache_limit: int = 0
    pending_retries: int = 0
    prefetch_requested: int = 0
    prefetch_completed: int = 0
    prefetch_failed: int = 0
    last_prefetch_ms: float | None = None
    colorize_last_ms: float | None = None
    colorize_avg_ms: float | None = None
    colorize_max_ms: float | None = None
    colorize_samples: int = 0
    colorize_slow_count: int = 0
    colorize_threshold_ms: float = 25.0
    colorize_last_source: str | None = None


@dataclass(frozen=True, slots=True)
class MaskRenderCacheKey:
    """Stable identity for one cached colorized mask render."""

    mask_id: uuid.UUID
    render_revision: int
    scale_key: float | None
    patch_bounds: RasterBounds | None = None

    def __post_init__(self) -> None:
        """Validate cache-key revision metadata."""
        if self.render_revision < 0:
            raise ValueError("mask render revision must be non-negative")


class MaskRenderCache:
    """Own colorized overlay derivation, caching, and cache diagnostics."""

    def __init__(
        self,
        assets: MaskAssetStore,
        source_to_panel_point: Callable[[QPoint], QPoint | QPointF | None],
        config: Config,
        mask_config: MaskConfigSlice,
        *,
        live_previews: MaskLivePreviewStore,
        active_mask_id: Callable[[], uuid.UUID | None],
        async_epoch: Callable[[uuid.UUID], int],
        color_for_mask: Callable[[uuid.UUID | None], QColor],
        render_changed: Callable[[uuid.UUID | None, QRect], None],
        active_properties_changed: Callable[[], None],
    ) -> None:
        """Initialize derived-render state and injected domain lookups."""
        self._assets = assets
        self._source_to_panel_point = source_to_panel_point
        self._config_source = config
        self._mask_config = mask_config
        self._shared_live_previews = live_previews
        self._active_mask_id = active_mask_id
        self._async_epoch = async_epoch
        self._color_for_mask = color_for_mask
        self._render_changed = render_changed
        self._active_properties_changed = active_properties_changed
        self._rasterizer = MaskRasterizer()
        self._cache: OrderedDict[MaskRenderCacheKey, QPixmap] = OrderedDict()
        self._entry_bytes: dict[MaskRenderCacheKey, int] = {}
        self._total_bytes = 0
        self._mask_index: dict[uuid.UUID, set[MaskRenderCacheKey]] = {}
        self._requested_scales: dict[uuid.UUID, float] = {}
        self._live_previews: dict[uuid.UUID, LiveMaskPreviewRaster] = {}
        self._live_preview_products: dict[uuid.UUID, QPixmap] = {}
        self._preview_geometry_revisions: dict[uuid.UUID, int] = {}
        self._prefetched_images: OrderedDict[uuid.UUID, QImage] = OrderedDict()
        self._prefetched_scaled: OrderedDict[uuid.UUID, OrderedDict[float, QImage]] = (
            OrderedDict()
        )
        self._prefetch_limit = 8
        self._async_handler: Callable[[uuid.UUID, MaskLayer], bool] | None = None
        self._async_pending: dict[uuid.UUID, int] = {}
        self._async_threshold_px = 512 * 512
        self._usage_callback: Callable[[], None] | None = None
        self._usage_batch_depth = 0
        self._usage_notification_pending = False
        self._admission_guard: Callable[[int], bool] | None = None
        self._rejected_keys: set[MaskRenderCacheKey] = set()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._evicted_bytes = 0
        self._last_eviction_reason: str | None = None
        self._last_eviction_timestamp: float | None = None
        self._prefetch_requested = 0
        self._prefetch_completed = 0
        self._prefetch_failed = 0
        self._last_prefetch_ms: float | None = None
        self._colorize_last_ms: float | None = None
        self._colorize_avg_ms: float | None = None
        self._colorize_total_ms = 0.0
        self._colorize_max_ms: float | None = None
        self._colorize_samples = 0
        self._colorize_slow_count = 0
        self._colorize_threshold_ms = 25.0
        self._colorize_last_source: str | None = None

    @property
    def cache_usage_bytes(self) -> int:
        """Return bytes consumed by cached colorized masks."""
        return self._total_bytes

    @property
    def evictable_cache_usage_bytes(self) -> int:
        """Return cached bytes excluding the active mask's required working set."""

        active_id = self._active_mask_id()
        return sum(
            size for key, size in self._entry_bytes.items() if key.mask_id != active_id
        )

    def active_mask_changed(self) -> None:
        """Reconcile cache eligibility after the protected active mask changes."""

        active_id = self._active_mask_id()
        self._evict_to_budget(set() if active_id is None else {active_id})
        self._notify_usage()

    def apply_config(
        self, config: Config, mask_config: MaskConfigSlice | None = None
    ) -> None:
        """Apply cache and raster-presentation settings."""
        previous_border = self._mask_config.mask_border_enabled
        self._config_source = config
        self._mask_config = mask_config or require_mask_config(config)
        if previous_border == self._mask_config.mask_border_enabled:
            return
        self.clear()
        active_id = self._active_mask_id()
        if active_id is not None:
            self.warm_requested(active_id)
            self._render_changed(active_id, QRect())

    def render_revision(self, mask_id: uuid.UUID) -> int:
        """Return a value-derived content and appearance cache identity."""
        layer = self._assets.get_layer(mask_id)
        surface_generation = (
            0 if layer is None else max(0, layer.coverage.raster.generation)
        )
        retained_revision = (
            0 if layer is None else max(0, layer.coverage.retained.revision)
        )
        appearance = int(self._color_for_mask(mask_id).rgba())
        border_enabled = int(bool(self._mask_config.mask_border_enabled))
        preview_geometry_revision = self._preview_geometry_revisions.get(mask_id, 0)
        return (
            surface_generation
            | (retained_revision << 32)
            | (max(0, self._async_epoch(mask_id)) << 64)
            | (appearance << 96)
            | (border_enabled << 128)
            | (preview_geometry_revision << 129)
        )

    def effective_source_bounds(self, mask_id: uuid.UUID) -> RasterBounds | None:
        """Return durable geometry united with separately composed preview pixels."""
        layer = self._assets.get_layer(mask_id)
        durable = None if layer is None else layer.coverage.source_bounds()
        preview = self._shared_live_previews.preview(mask_id)
        return durable if preview is None else preview.presentation_bounds(durable)

    def preview_stride(self, mask_id: uuid.UUID, viewport_zoom: float) -> int:
        """Return a preview stride satisfying the active render resolution."""
        layer = self._assets.get_layer(mask_id)
        if layer is not None:
            storage_bounds = layer.coverage.raster.bounds
            source_bounds = layer.coverage.source_bounds()
            if storage_bounds is not None and storage_bounds != source_bounds:
                return 1
        viewport_scale = max(1e-6, float(viewport_zoom))
        viewport_density = min(
            1.0,
            2.0 ** math.ceil(math.log2(viewport_scale)),
        )
        required_scale = max(
            viewport_density,
            self._requested_scales.get(mask_id, viewport_density),
        )
        return 1 if required_scale >= 1.0 else max(1, round(1 / required_scale))

    def is_live_preview(self, mask_id: uuid.UUID) -> bool:
        """Return whether cached pixels include an in-flight provisional preview."""
        return mask_id in self._live_previews or self._shared_live_previews.contains(
            mask_id
        )

    def uses_local_live_preview(self, mask_id: uuid.UUID) -> bool:
        """Return whether this view renders a decimated provisional product."""
        return mask_id in self._live_previews

    def live_preview_patches(
        self,
        mask_id: uuid.UUID,
    ) -> LiveMaskPreviewPatches | None:
        """Return native provisional patches for region-sampled presentation."""
        return self._shared_live_previews.preview(mask_id)

    def notify_live_preview_changed(
        self,
        mask_id: uuid.UUID,
        storage_rect: QRect,
    ) -> None:
        """Project shared provisional damage through this view's coordinates."""
        if storage_rect.isNull() or storage_rect.isEmpty():
            self._render_changed(mask_id, QRect())
            return
        self._emit_dirty_rect(mask_id, storage_rect)

    def advance_preview_geometry(self, mask_id: uuid.UUID) -> None:
        """Advance source identity after the provisional envelope changes."""
        self._preview_geometry_revisions[mask_id] = (
            self._preview_geometry_revisions.get(mask_id, 0) + 1
        )

    def discard_live_preview(self, mask_id: uuid.UUID) -> None:
        """Release every provisional product owned for one mask."""
        self._discard_live_preview(mask_id)

    def prepare_live_preview_settlement(self, mask_id: uuid.UUID) -> bool:
        """Promote shared provisional pixels into durable handoff state."""
        return self._shared_live_previews.prepare_settlement(mask_id)

    def discard_source(self, mask_id: uuid.UUID) -> None:
        """Forget render state associated with a deleted source."""
        self.cancel_async(mask_id)
        self._requested_scales.pop(mask_id, None)
        self._preview_geometry_revisions.pop(mask_id, None)
        self._discard_local_live_preview(mask_id)
        self._shared_live_previews.discard(mask_id)
        self.invalidate(mask_id)

    def set_cache_usage_callback(self, callback: Callable[[], None] | None) -> None:
        """Register a callback invoked whenever cache usage changes."""
        self._usage_callback = callback
        if callback is not None:
            self._notify_usage()

    def set_admission_guard(self, guard: Callable[[int], bool] | None) -> None:
        """Install an optional cache-admission guard."""
        self._admission_guard = guard

    def cache_limit_bytes(self) -> int:
        """Return the configured mask cache budget."""
        settings = getattr(self._config_source, "cache", None)
        if not isinstance(settings, CacheSettings):
            settings = CacheSettings()
        return max(
            0,
            int(
                settings.resolved_consumer_budgets_bytes(
                    active_consumers={
                        "tiles",
                        "pyramids",
                        "mask_overlays",
                        "models",
                    }
                ).get("mask_overlays", 0)
            ),
        )

    def hybrid_style(self, mask_id: uuid.UUID) -> HybridPresentationStyle:
        """Return immutable presentation values for QPane hybrid sampling."""
        color = QColor(self._color_for_mask(mask_id))
        color.setAlpha(255)
        outline = color.darker(120) if self._mask_config.mask_border_enabled else None
        return HybridPresentationStyle(color, outline)

    def record_prefetch_request(self, count: int) -> None:
        """Record scheduled derived-raster prefetch work."""
        if count > 0:
            self._prefetch_requested += count

    def record_prefetch_completion(
        self,
        *,
        completed: int,
        failed: int = 0,
        duration_ms: float | None = None,
    ) -> None:
        """Record completion of derived-raster prefetch work."""
        self._prefetch_completed += max(0, completed)
        self._prefetch_failed += max(0, failed)
        if duration_ms is not None:
            self._last_prefetch_ms = duration_ms
        self._notify_usage()

    def set_async_handler(
        self,
        handler: Callable[[uuid.UUID, MaskLayer], bool] | None,
        *,
        threshold_px: int | None = None,
    ) -> None:
        """Set the background colorization scheduler."""
        self._async_handler = handler
        if threshold_px is not None and threshold_px > 0:
            self._async_threshold_px = threshold_px

    def complete_async(self, mask_id: uuid.UUID, render_revision: int) -> None:
        """Finish the matching asynchronous raster request."""
        if self._async_pending.get(mask_id) == render_revision:
            self._async_pending.pop(mask_id, None)

    def cancel_async(self, mask_id: uuid.UUID) -> None:
        """Cancel asynchronous raster ownership for a source."""
        self._async_pending.pop(mask_id, None)

    def has_pending_async(self, mask_id: uuid.UUID | None = None) -> bool:
        """Return whether async rasterization owns pending work."""
        return (
            bool(self._async_pending)
            if mask_id is None
            else mask_id in self._async_pending
        )

    def normalize_scale(self, scale: float | None) -> float | None:
        """Normalize a requested render scale for stable cache identity."""
        try:
            value = None if scale is None else float(scale)
        except (TypeError, ValueError):
            return None
        if value is None or value <= 0 or abs(value - 1.0) < 1e-3:
            return None
        return round(value, 4)

    def target_scaled_size(self, size: QSize, scale: float) -> QSize:
        """Return the integer size produced by a scale."""
        return QSize(
            max(1, round(size.width() * scale)), max(1, round(size.height() * scale))
        )

    def prepare_image(
        self,
        layer: MaskLayer,
        *,
        mask_id: uuid.UUID | None = None,
        source: str = "prefetch",
    ) -> QImage | None:
        """Build a colorized image suitable for background prefetch."""
        if layer.coverage.has_retained_items:
            return None
        image = layer.coverage.snapshot_qimage()
        if image.isNull():
            return None
        resolved_id = layer.mask_id if mask_id is None else mask_id
        return self.colorize_image(
            image,
            self._color_for_mask(resolved_id),
            mask_id=resolved_id,
            source=source,
        )

    def prepare_image_detached(
        self,
        layer: MaskLayer,
        *,
        mask_id: uuid.UUID | None = None,
    ) -> QImage | None:
        """Build a worker-safe product without mutating UI-owned cache state."""
        if layer.coverage.has_retained_items:
            return None
        image = layer.coverage.snapshot_qimage()
        if image.isNull():
            return None
        resolved_id = layer.mask_id if mask_id is None else mask_id
        return self.rasterize_detached(image, self._color_for_mask(resolved_id))

    def rasterize_detached(self, mask_image: QImage, color: QColor) -> QImage:
        """Colorize detached pixels without cache accounting or UI publication."""
        return self._rasterizer.rasterize(
            mask_image,
            color,
            draw_border=self._mask_config.mask_border_enabled,
        )

    def commit_prefetched(
        self,
        mask_id: uuid.UUID,
        layer: MaskLayer,
        image: QImage,
        *,
        scaled: Sequence[tuple[float, QImage]] | None = None,
    ) -> None:
        """Promote completed background rasters into the UI-thread cache."""
        if layer is None or image.isNull():
            return
        self._store_prefetched(mask_id, image)
        self._store_prefetched_scaled(mask_id, scaled)
        key = self._key(mask_id, None)
        if key not in self._cache:
            self._misses += 1
            self._insert(key, QPixmap.fromImage(image), mask_id=mask_id)
        for scale, scaled_image in scaled or ():
            scale_key = self.normalize_scale(scale)
            if scale_key is None or scaled_image.isNull():
                continue
            scaled_key = self._key(mask_id, scale_key)
            if scaled_key not in self._cache:
                self._insert(
                    scaled_key, QPixmap.fromImage(scaled_image), mask_id=mask_id
                )
        self._render_changed(mask_id, QRect())

    def commit_native(
        self,
        mask_id: uuid.UUID,
        layer: MaskLayer,
        image: QImage,
    ) -> None:
        """Admit one completed native presentation and publish its availability."""
        bounds = None if layer is None else layer.coverage.source_bounds()
        if (
            layer is None
            or bounds is None
            or image.isNull()
            or image.size() != QSize(bounds.width, bounds.height)
        ):
            return
        key = self._key(mask_id, None)
        if key not in self._cache:
            self._misses += 1
            self._insert(key, QPixmap.fromImage(image), mask_id=mask_id)
        self._render_changed(mask_id, QRect())

    def notify_color_changed(self, mask_id: uuid.UUID) -> None:
        """Invalidate derived rasters after a tint change."""
        self.invalidate(mask_id)
        self.warm_requested(mask_id)
        self._active_properties_changed()
        self._render_changed(mask_id, QRect())

    def notify_opacity_changed(self, mask_id: uuid.UUID) -> None:
        """Notify observers after composition changes source opacity."""
        self._active_properties_changed()
        self._render_changed(mask_id, QRect())

    def invalidate(
        self, mask_id: uuid.UUID | None, *, reason: str = "invalidate"
    ) -> None:
        """Invalidate every cached scale for a source."""
        if mask_id is None:
            return
        self._discard_local_live_preview(mask_id)
        self._forget_prefetched(mask_id)
        for key in list(self._mask_index.get(mask_id, ())):
            self._drop(key, reason=reason)

    def invalidate_layer(self, layer: MaskLayer | None) -> None:
        """Invalidate the layer's derived rasters."""
        if layer is not None:
            self.invalidate(layer.mask_id)

    def warm(self, mask_id: uuid.UUID | None, *, scale: float | None = None) -> None:
        """Generate the currently useful cached raster for a source when present."""
        if mask_id is None:
            return
        layer = self._assets.get_layer(mask_id)
        if layer is not None and not layer.coverage.has_retained_items:
            self.get(layer, scale=scale)

    def warm_requested(self, mask_id: uuid.UUID | None) -> None:
        """Warm the density most recently requested by the active view."""
        if mask_id is None:
            return
        self.warm(mask_id, scale=self._requested_scales.get(mask_id))

    def get(self, layer: MaskLayer, *, scale: float | None = None) -> QPixmap | None:
        """Return a colorized cached raster for a layer."""
        return self._get(layer, scale=scale)

    def get_with_live_preview(
        self,
        layer: MaskLayer,
        *,
        scale: float | None = None,
    ) -> QPixmap | None:
        """Return an explicit full product including provisional native coverage."""
        preview = self._shared_live_previews.preview(layer.mask_id)
        if preview is None:
            return self._get(layer, scale=scale)
        snapshot = layer.coverage.snapshot()
        bounds = snapshot.bounds
        if bounds is None:
            return None
        pixels = np.array(snapshot.pixels, copy=True, order="C")
        preview.apply_to(bounds, pixels)
        scale_key = self.normalize_scale(scale)
        target_size = (
            None
            if scale_key is None
            else self.target_scaled_size(QSize(bounds.width, bounds.height), scale_key)
        )
        return QPixmap.fromImage(
            self.present_pixels(layer.mask_id, pixels, target_size)
        )

    def get_by_id_with_live_preview(
        self,
        mask_id: uuid.UUID,
        *,
        scale: float | None = None,
    ) -> QPixmap | None:
        """Return an explicit full provisional product for one source ID."""
        layer = self._assets.get_layer(mask_id)
        return None if layer is None else self.get_with_live_preview(layer, scale=scale)

    def get_by_id(
        self, mask_id: uuid.UUID, *, scale: float | None = None
    ) -> QPixmap | None:
        """Return a cached raster for a source id."""
        layer = self._assets.get_layer(mask_id)
        if layer is None:
            return None
        scale_key = self.normalize_scale(scale)
        if scale_key is not None:
            self._requested_scales[mask_id] = scale_key
        return self._get(layer, scale=scale)

    def peek_by_id(
        self, mask_id: uuid.UUID, *, scale: float | None = None
    ) -> QPixmap | None:
        """Return an existing render product without deriving or scheduling one."""
        if self._assets.get_layer(mask_id) is None:
            return None
        scale_key = self.normalize_scale(scale)
        key = self._key(mask_id, scale_key)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            self._hits += 1
            return cached
        live_preview = self._live_preview_pixmap(mask_id, scale_key)
        if live_preview is not None:
            self._hits += 1
        return live_preview

    def get_best_by_id(self, mask_id: uuid.UUID, *, scale: float) -> QPixmap | None:
        """Reuse a current nearby LOD before deriving another sampled raster."""
        layer = self._assets.get_layer(mask_id)
        if layer is None:
            return None
        requested = self.normalize_scale(scale)
        requested_density = 1.0 if requested is None else requested
        self._requested_scales[mask_id] = requested_density
        exact = self.peek_by_id(mask_id, scale=requested)
        if exact is not None:
            return exact
        revision = self.render_revision(mask_id)
        candidates = tuple(
            (1.0 if scale_key is None else scale_key, key, pixmap)
            for scale_key, (key, pixmap, _size) in self._latest_entries(mask_id).items()
            if key.render_revision == revision
        )
        if candidates:
            density, key, pixmap = min(
                candidates,
                key=lambda candidate: abs(math.log2(candidate[0] / requested_density)),
            )
            ratio = density / requested_density
            if 0.5 <= ratio <= 2.0:
                self._cache.move_to_end(key)
                self._hits += 1
                return pixmap
        derived = self._get(layer, scale=scale)
        if derived is not None or not candidates:
            return derived
        _density, key, fallback = min(
            candidates,
            key=lambda candidate: abs(math.log2(candidate[0] / requested_density)),
        )
        self._cache.move_to_end(key)
        self._hits += 1
        return fallback

    def update_region(
        self,
        dirty_rect: QRect,
        layer: MaskLayer,
        *,
        sub_mask_image: QImage | None = None,
        colorized_image: QImage | None = None,
    ) -> None:
        """Patch live cached rasters for one changed source region."""
        if layer is None or dirty_rect.isNull() or dirty_rect.isEmpty():
            return
        mask_id = layer.mask_id
        preview_stride: int | None = None
        preview_provisional = False
        if sub_mask_image is not None:
            try:
                preview_stride = int(sub_mask_image.text("qpane_preview_stride"))
            except (TypeError, ValueError):
                preview_stride = None
            preview_provisional = (
                sub_mask_image.text("qpane_preview_provisional") == "1"
            )
        if preview_provisional:
            if preview_stride is not None and sub_mask_image is not None:
                self._update_live_preview(
                    dirty_rect,
                    layer,
                    sub_mask_image,
                    stride=preview_stride,
                )
                return
        else:
            self._discard_live_preview(mask_id)
        base_key = self._key(mask_id, None)
        base_pixmap = self._cache.get(base_key)
        if preview_stride is not None and preview_stride > 1:
            if base_pixmap is not None:
                self._drop(base_key, reason="decimated_preview")
            base_pixmap = None
        self._forget_prefetched(mask_id)
        if colorized_image is not None and not colorized_image.isNull():
            colorized = colorized_image
        else:
            region = sub_mask_image or layer.mask_image.copy(dirty_rect)
            colorized = self.colorize_image(
                region,
                self._color_for_mask(mask_id),
                mask_id=mask_id,
                source="snippet_provisional" if preview_provisional else "snippet",
            )
        snippet = QPixmap.fromImage(colorized)
        if base_pixmap is not None and not base_pixmap.isNull():
            painter = QPainter(base_pixmap)
            painter.setCompositionMode(QPainter.CompositionMode_Source)
            destination = storage_damage_destination(
                layer.coverage.raster.bounds,
                layer.coverage.source_bounds(),
                dirty_rect,
                1.0,
            )
            if destination is not None:
                painter.drawPixmap(destination.topLeft(), snippet)
            painter.end()
        preview_scale = (
            None if not preview_stride or preview_stride <= 1 else 1 / preview_stride
        )
        for key in tuple(self._mask_index.get(mask_id, set())):
            scale_key = key.scale_key
            if scale_key is None:
                continue
            if preview_scale is not None and scale_key > preview_scale + 1e-4:
                self._drop(key, reason="decimated_preview")
                continue
            cached = self._cache.get(key)
            if cached is None or cached.isNull():
                continue
            destination = storage_damage_destination(
                layer.coverage.raster.bounds,
                layer.coverage.source_bounds(),
                dirty_rect,
                scale_key,
            )
            if destination is None:
                continue
            painter = QPainter(cached)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.setCompositionMode(QPainter.CompositionMode_Source)
            painter.drawPixmap(
                destination, snippet, QRect(QPoint(0, 0), snippet.size())
            )
            painter.end()
        self._emit_dirty_rect(mask_id, dirty_rect)

    def apply_history_delta(self, layer: MaskLayer, change: MaskHistoryChange) -> bool:
        """Apply canonical undo/redo pixels to existing cached rasters."""
        if not change.snippets:
            return False
        latest = self._latest_entries(layer.mask_id)
        if not latest:
            return False
        surface = layer.coverage.raster
        surface_bounds = surface.bounds
        if surface_bounds is None:
            return False
        mask_rect = QRect(0, 0, surface_bounds.width, surface_bounds.height)
        dirty_rects: list[QRect] = []
        for snippet in change.snippets:
            rect = snippet.rect.normalized().intersected(mask_rect)
            if self._mask_config.mask_border_enabled:
                rect = rect.adjusted(-1, -1, 1, 1).intersected(mask_rect)
            if not rect.isNull() and not rect.isEmpty():
                dirty_rects.append(rect)
        if not dirty_rects:
            return False
        for rect in dirty_rects:
            pixels = surface.snapshot_storage_region(
                RasterBounds(
                    rect.x(),
                    rect.y(),
                    rect.width(),
                    rect.height(),
                )
            )
            image = self.colorize_image(
                numpy_to_qimage_grayscale8(pixels),
                self._color_for_mask(layer.mask_id),
                mask_id=layer.mask_id,
                source="history_snippet",
            )
            snippet = QPixmap.fromImage(image)
            for scale_key, (_key, cached, _size) in latest.items():
                painter = QPainter(cached)
                painter.setCompositionMode(QPainter.CompositionMode_Source)
                if scale_key is None:
                    destination = storage_damage_destination(
                        layer.coverage.raster.bounds,
                        layer.coverage.source_bounds(),
                        rect,
                        1.0,
                    )
                    if destination is not None:
                        painter.drawPixmap(destination.topLeft(), snippet)
                else:
                    painter.setRenderHint(
                        QPainter.RenderHint.SmoothPixmapTransform, True
                    )
                    destination = storage_damage_destination(
                        layer.coverage.raster.bounds,
                        layer.coverage.source_bounds(),
                        rect,
                        scale_key,
                    )
                    if destination is None:
                        painter.end()
                        continue
                    painter.drawPixmap(
                        destination, snippet, QRect(QPoint(0, 0), snippet.size())
                    )
                painter.end()
        self.promote_revision(layer.mask_id)
        dirty = QRect(dirty_rects[0])
        for rect in dirty_rects[1:]:
            dirty = dirty.united(rect)
        self._emit_dirty_rect(layer.mask_id, dirty)
        return True

    def promote_revision(self, mask_id: uuid.UUID) -> None:
        """Carry live cache surfaces into the source's current revision."""
        keys = tuple(self._mask_index.get(mask_id, set()))
        if not keys:
            return
        retained = {
            scale: (pixmap, size)
            for scale, (_key, pixmap, size) in self._latest_entries(mask_id).items()
        }
        for key in keys:
            self._cache.pop(key, None)
            self._total_bytes = max(
                0, self._total_bytes - self._entry_bytes.pop(key, 0)
            )
        self._mask_index.pop(mask_id, None)
        for scale_key, (pixmap, size) in retained.items():
            if pixmap is None or pixmap.isNull():
                continue
            key = self._key(mask_id, scale_key)
            self._cache[key] = pixmap
            self._entry_bytes[key] = size
            self._total_bytes += size
            self._mask_index.setdefault(mask_id, set()).add(key)
        self._notify_usage()

    def snapshot_metrics(self) -> MaskOverlayMetrics:
        """Return immutable cache diagnostics."""
        return MaskOverlayMetrics(
            cache_bytes=self._total_bytes,
            entry_count=len(self._cache),
            hits=self._hits,
            misses=self._misses,
            evictions=self._evictions,
            evicted_bytes=self._evicted_bytes,
            last_eviction_reason=self._last_eviction_reason,
            last_eviction_timestamp=self._last_eviction_timestamp,
            prefetch_requested=self._prefetch_requested,
            prefetch_completed=self._prefetch_completed,
            prefetch_failed=self._prefetch_failed,
            last_prefetch_ms=self._last_prefetch_ms,
            colorize_last_ms=self._colorize_last_ms,
            colorize_avg_ms=self._colorize_avg_ms,
            colorize_max_ms=self._colorize_max_ms,
            colorize_samples=self._colorize_samples,
            colorize_slow_count=self._colorize_slow_count,
            colorize_threshold_ms=self._colorize_threshold_ms,
            colorize_last_source=self._colorize_last_source,
        )

    def clear(self) -> None:
        """Clear all derived raster entries."""
        for key in list(self._cache):
            self._drop(key, reason="clear")
        self._cache.clear()
        self._entry_bytes.clear()
        self._total_bytes = 0
        self._rejected_keys.clear()
        self._live_previews.clear()
        self._live_preview_products.clear()
        self._notify_usage()

    def drop_oldest(self, *, reason: str, exclude: set[uuid.UUID] | None = None) -> int:
        """Evict the least-recently-used eligible source raster."""
        excluded = set(exclude or ())
        active_id = self._active_mask_id()
        if active_id is not None:
            excluded.add(active_id)
        for key in list(self._cache):
            if key.mask_id not in excluded:
                return self._drop(key, reason=reason)
        return 0

    def colorize_image(
        self,
        mask_image: QImage,
        color: QColor,
        *,
        mask_id: uuid.UUID | None,
        source: str | None,
    ) -> QImage:
        """Rasterize a grayscale mask and record duration metrics."""
        normalized_source = source or "cache_miss"
        started = time.perf_counter()
        result = self._rasterizer.rasterize(
            mask_image,
            color,
            draw_border=self._mask_config.mask_border_enabled,
        )
        duration_ms = (time.perf_counter() - started) * 1000
        self._record_colorize(duration_ms, source=normalized_source)
        if mask_id is not None and (
            normalized_source == "cache_miss"
            or normalized_source.startswith("prefetch")
        ):
            self._store_prefetched(mask_id, result)
        return result

    def record_background_colorize(self, duration_ms: float, *, source: str) -> None:
        """Publish worker rasterization metrics on the UI-owned cache boundary."""
        self._record_colorize(max(0.0, float(duration_ms)), source=source)

    def present_pixels(
        self,
        mask_id: uuid.UUID,
        pixels: np.ndarray,
        target_size: QSize | None = None,
    ) -> QImage:
        """Colorize detached canonical pixels without admitting them to the cache."""
        image = (
            numpy_to_qimage_grayscale8(pixels)
            if target_size is None
            else preview_mask_coverage(pixels, target_size)
        )
        return self.colorize_image(
            image,
            self._color_for_mask(mask_id),
            mask_id=None,
            source="floating_edit",
        )

    def present_patch(
        self,
        mask_id: uuid.UUID,
        bounds: RasterBounds,
        pixels_with_bleed: np.ndarray,
    ) -> QImage:
        """Return one revision-keyed colorized tile including its one-pixel bleed."""
        key = self._key(mask_id, None, patch_bounds=bounds)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            self._hits += 1
            return cached.toImage()
        expected = (bounds.height + 2, bounds.width + 2)
        if pixels_with_bleed.shape != expected:
            raise ValueError(f"mask patch bleed pixels must match {expected}")
        image = numpy_to_qimage_grayscale8(pixels_with_bleed)
        colorized = self.colorize_image(
            image,
            self._color_for_mask(mask_id),
            mask_id=None,
            source="sparse_patch",
        )
        self._misses += 1
        self._insert(key, QPixmap.fromImage(colorized), mask_id=mask_id)
        return colorized

    def _key(
        self,
        mask_id: uuid.UUID,
        scale_key: float | None,
        *,
        patch_bounds: RasterBounds | None = None,
    ) -> MaskRenderCacheKey:
        """Build one stable cache key."""
        return MaskRenderCacheKey(
            mask_id,
            self.render_revision(mask_id),
            scale_key,
            patch_bounds,
        )

    def _get(self, layer: MaskLayer, *, scale: float | None = None) -> QPixmap | None:
        """Resolve, derive, and cache one requested raster."""
        mask_id = layer.mask_id
        scale_key = self.normalize_scale(scale)
        key = self._key(mask_id, scale_key)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            self._hits += 1
            return cached
        live_preview = self._live_preview_pixmap(mask_id, scale_key)
        if live_preview is not None:
            self._hits += 1
            return live_preview
        if scale_key is not None:
            stored = self._prefetched_scaled.get(mask_id, {}).get(scale_key)
            if stored is not None and not stored.isNull():
                self._hits += 1
                result = QPixmap.fromImage(stored)
                self._insert(key, result, mask_id=mask_id)
                return result
            base = self._cache.get(self._key(mask_id, None))
            if base is not None:
                target_size = self.target_scaled_size(base.size(), scale_key)
                result = QPixmap.fromImage(
                    preview_mask_overlay(base.toImage(), target_size)
                )
            else:
                result = self._scaled_surface_pixmap(layer, scale_key)
            self._misses += 1
            self._insert(key, result, mask_id=mask_id)
            return result
        image = layer.coverage.snapshot_qimage()
        if image.isNull():
            return None
        if scale_key is None:
            stored = self._prefetched_images.get(mask_id)
            if stored is not None and not stored.isNull():
                self._hits += 1
                result = QPixmap.fromImage(stored)
                self._insert(key, result, mask_id=mask_id)
                return result
            elif self._async_handler is not None and (
                image.width() * image.height() > self._async_threshold_px
            ):
                if self._async_pending.get(mask_id) == key.render_revision:
                    return None
                self._async_pending[mask_id] = key.render_revision
                try:
                    if self._async_handler(mask_id, layer):
                        return None
                except Exception:
                    logger.exception(
                        "Async colorize handler failed for mask %s", mask_id
                    )
                self._async_pending.pop(mask_id, None)
                result = self._colorize_pixmap(image, mask_id, "cache_miss")
            else:
                result = self._colorize_pixmap(image, mask_id, "cache_miss")
        self._misses += 1
        self._insert(key, result, mask_id=mask_id)
        return result

    def _live_preview_pixmap(
        self,
        mask_id: uuid.UUID,
        requested_scale: float | None,
    ) -> QPixmap | None:
        """Return the nearest cache containing an in-flight stroke preview."""
        if mask_id not in self._live_previews:
            return None
        del requested_scale
        product = self._live_preview_products.get(mask_id)
        if product is None or product.isNull():
            return None
        return product

    def _update_live_preview(
        self,
        dirty_rect: QRect,
        layer: MaskLayer,
        patch: QImage,
        *,
        stride: int,
    ) -> None:
        """Accumulate and publish one provisional patch on a stable sample lattice."""
        mask_id = layer.mask_id
        surface = layer.coverage.raster
        bounds = surface.bounds
        if bounds is None:
            return
        normalized_stride = max(1, int(stride))
        if normalized_stride == 1:
            self._live_previews.pop(mask_id, None)
            self._live_preview_products.pop(mask_id, None)
            self._forget_prefetched(mask_id)
            self._shared_live_previews.apply_patch(
                mask_id,
                bounds,
                dirty_rect,
                patch,
            )
            return
        self._shared_live_previews.discard(mask_id)
        preview = self._live_previews.get(mask_id)
        source_size = QSize(bounds.width, bounds.height)
        if (
            preview is None
            or preview.stride != normalized_stride
            or preview.source_size != source_size
        ):
            pixels = surface.snapshot_storage_region(
                RasterBounds(0, 0, bounds.width, bounds.height),
                stride=normalized_stride,
            )
            preview = LiveMaskPreviewRaster(
                source_size=source_size,
                stride=normalized_stride,
                base_pixels=pixels,
            )
            self._live_previews[mask_id] = preview

        preview_scale = self.normalize_scale(1.0 / normalized_stride)
        preview_key = self._key(mask_id, preview_scale)
        target = self._live_preview_products.get(mask_id)
        if target is None or target.isNull() or target.size() != preview.image.size():
            if surface.content_bounds() is None:
                target = QPixmap(preview.image.size())
                target.fill(QColor(0, 0, 0, 0))
            else:
                target = self._colorize_pixmap(
                    preview.image,
                    mask_id,
                    "preview_base",
                )
            self._live_preview_products[mask_id] = target
            self._insert(preview_key, target, mask_id=mask_id)

        for key in tuple(self._mask_index.get(mask_id, set())):
            if key != preview_key and key.patch_bounds is None:
                self._drop(key, reason="live_preview_density")

        update = preview.apply_patch(dirty_rect, patch)
        colorized_context = self.colorize_image(
            update.context,
            self._color_for_mask(mask_id),
            mask_id=None,
            source="snippet_provisional",
        )
        colorized = colorized_context.copy(update.context_core)
        painter = QPainter(target)
        target_scale = 1.0 if preview_scale is None else preview_scale
        source_rect = preview.source_rect(update.destination)
        destination = scaled_source_rect(source_rect, target_scale)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.drawImage(destination.topLeft(), colorized)
        painter.end()
        self._cache[preview_key] = target
        self._cache.move_to_end(preview_key)
        self._forget_prefetched(mask_id)
        self._emit_dirty_rect(mask_id, source_rect)

    def _discard_live_preview(self, mask_id: uuid.UUID) -> None:
        """Release volatile coverage and its revision-independent product together."""
        self._discard_local_live_preview(mask_id)
        self._shared_live_previews.discard(mask_id)

    def _discard_local_live_preview(self, mask_id: uuid.UUID) -> None:
        """Release view-specific decimated products without changing shared state."""
        self._live_previews.pop(mask_id, None)
        self._live_preview_products.pop(mask_id, None)

    def _scaled_surface_pixmap(
        self,
        layer: MaskLayer,
        scale: float,
    ) -> QPixmap:
        """Derive one scaled overlay without copying the full mask surface."""
        bounds = layer.coverage.source_bounds()
        if bounds is None:
            return QPixmap()
        source_size = QSize(bounds.width, bounds.height)
        target_size = self.target_scaled_size(source_size, scale)
        if layer.coverage.has_retained_items:
            pixels = layer.coverage.snapshot(bounds).pixels
            scaled = preview_mask_coverage(pixels, target_size)
        else:
            stride = max(
                1,
                math.ceil(bounds.width / (target_size.width() * 2)),
                math.ceil(bounds.height / (target_size.height() * 2)),
            )
            pixels = layer.coverage.raster.capture_region_strided(bounds, stride)
            scaled = preview_mask_coverage(pixels, target_size)
        return self._colorize_pixmap(scaled, layer.mask_id, "scaled_cache_miss")

    def _colorize_pixmap(
        self, image: QImage, mask_id: uuid.UUID, source: str
    ) -> QPixmap:
        """Return a colorized pixmap for one source image."""
        return QPixmap.fromImage(
            self.colorize_image(
                image,
                self._color_for_mask(mask_id),
                mask_id=mask_id,
                source=source,
            )
        )

    def _store_prefetched(self, mask_id: uuid.UUID, image: QImage) -> None:
        """Retain a detached prefetch result until UI-thread promotion."""
        if image.isNull():
            return
        self._prefetched_images[mask_id] = image
        self._prefetched_images.move_to_end(mask_id)
        while len(self._prefetched_images) > self._prefetch_limit:
            stale_id, _ = self._prefetched_images.popitem(last=False)
            self._prefetched_scaled.pop(stale_id, None)

    def _store_prefetched_scaled(
        self,
        mask_id: uuid.UUID,
        scaled: Sequence[tuple[float, QImage]] | None,
    ) -> None:
        """Retain scale-specific prefetch results."""
        bucket: OrderedDict[float, QImage] = OrderedDict()
        for scale, image in scaled or ():
            key = self.normalize_scale(scale)
            if key is not None and not image.isNull():
                bucket[key] = image
        if not bucket:
            return
        self._prefetched_scaled[mask_id] = bucket
        self._prefetched_scaled.move_to_end(mask_id)
        while len(self._prefetched_scaled) > self._prefetch_limit:
            stale_id, _ = self._prefetched_scaled.popitem(last=False)
            self._prefetched_images.pop(stale_id, None)

    def _forget_prefetched(self, mask_id: uuid.UUID) -> None:
        """Drop pending prefetched images for a source."""
        self._prefetched_images.pop(mask_id, None)
        self._prefetched_scaled.pop(mask_id, None)

    def _latest_entries(
        self, mask_id: uuid.UUID
    ) -> dict[float | None, tuple[MaskRenderCacheKey, QPixmap, int]]:
        """Return the newest usable entry at each scale."""
        latest: dict[float | None, tuple[MaskRenderCacheKey, QPixmap, int]] = {}
        for key in tuple(self._mask_index.get(mask_id, set())):
            if key.patch_bounds is not None:
                continue
            pixmap = self._cache.get(key)
            current = latest.get(key.scale_key)
            if (
                pixmap is not None
                and not pixmap.isNull()
                and (
                    current is None or key.render_revision > current[0].render_revision
                )
            ):
                latest[key.scale_key] = (key, pixmap, self._entry_bytes.get(key, 0))
        return latest

    def _insert(
        self, key: MaskRenderCacheKey, pixmap: QPixmap, *, mask_id: uuid.UUID
    ) -> None:
        """Insert one raster and enforce the configured budget."""
        size = self._estimate_bytes(pixmap)
        if not self._allow_insert(size, key):
            return
        self._total_bytes -= self._entry_bytes.get(key, 0)
        self._cache[key] = pixmap
        self._cache.move_to_end(key)
        self._entry_bytes[key] = size
        self._mask_index.setdefault(key.mask_id, set()).add(key)
        self._total_bytes += size
        excluded = {mask_id}
        active_id = self._active_mask_id()
        if active_id is not None:
            excluded.add(active_id)
        self._evict_to_budget(excluded)
        self._notify_usage()

    def _allow_insert(self, size: int, key: MaskRenderCacheKey) -> bool:
        """Return whether one raster fits cache-admission guardrails."""
        budget = self.cache_limit_bytes()
        allowed = size <= budget and (
            self._admission_guard is None or self._admission_guard(size)
        )
        if not allowed and key not in self._rejected_keys:
            logger.warning(
                "requested item exceeds budget; not cached | consumer=mask_overlays | size=%d | budget=%d",
                size,
                budget,
            )
            self._rejected_keys.add(key)
        return allowed

    def _drop(self, key: MaskRenderCacheKey, *, reason: str) -> int:
        """Remove one cached raster and return its byte size."""
        self._cache.pop(key, None)
        size = self._entry_bytes.pop(key, 0)
        bucket = self._mask_index.get(key.mask_id)
        if bucket is not None:
            bucket.discard(key)
            if not bucket:
                self._mask_index.pop(key.mask_id, None)
                self._prefetched_scaled.pop(key.mask_id, None)
        if size:
            self._total_bytes = max(0, self._total_bytes - size)
            self._evictions += 1
            self._evicted_bytes += size
            self._last_eviction_reason = reason
            self._last_eviction_timestamp = time.monotonic()
        self._notify_usage()
        return size

    def _evict_to_budget(self, excluded: set[uuid.UUID]) -> None:
        """Evict LRU entries until the cache fits its budget."""
        limit = self.cache_limit_bytes()
        attempts = 0
        while self._total_bytes > limit and attempts < len(self._cache):
            if self.drop_oldest(reason="capacity", exclude=excluded) <= 0:
                break
            attempts += 1

    @staticmethod
    def _estimate_bytes(pixmap: QPixmap) -> int:
        """Approximate a pixmap's memory footprint."""
        if pixmap is None or pixmap.isNull():
            return 0
        return pixmap.width() * pixmap.height() * ((pixmap.depth() or 32) // 8)

    def _record_colorize(self, duration_ms: float, *, source: str) -> None:
        """Update rasterization timing aggregates."""
        self._colorize_last_ms = duration_ms
        self._colorize_last_source = source
        self._colorize_total_ms += duration_ms
        self._colorize_samples += 1
        self._colorize_avg_ms = self._colorize_total_ms / self._colorize_samples
        self._colorize_max_ms = max(self._colorize_max_ms or 0, duration_ms)
        if duration_ms >= self._colorize_threshold_ms:
            self._colorize_slow_count += 1
            self._notify_usage()

    def _emit_dirty_rect(self, mask_id: uuid.UUID, image_rect: QRect) -> None:
        """Convert one changed image region to panel coordinates."""
        layer = self._assets.get_layer(mask_id)
        bounds = None if layer is None else layer.coverage.raster.bounds
        if bounds is None:
            self._render_changed(mask_id, QRect())
            return
        local_offset = QPoint(bounds.x, bounds.y)
        top_left = self._source_to_panel_point(image_rect.topLeft() + local_offset)
        bottom_right = self._source_to_panel_point(
            QPoint(image_rect.right() + 1, image_rect.bottom() + 1) + local_offset
        )
        if top_left is None or bottom_right is None:
            self._render_changed(mask_id, QRect())
            return
        panel_rect = QRectF(top_left, bottom_right).normalized().adjusted(-2, -2, 2, 2)
        self._render_changed(mask_id, panel_rect.toRect())

    def _notify_usage(self) -> None:
        """Notify cache coordination after an accounting change."""
        if self._usage_batch_depth > 0:
            self._usage_notification_pending = True
            return
        self._publish_usage()

    @contextmanager
    def _batch_usage_notifications(self) -> Iterator[None]:
        """Coalesce accounting callbacks across one atomic cache transition."""
        self._usage_batch_depth += 1
        try:
            yield
        finally:
            self._usage_batch_depth -= 1
            if self._usage_batch_depth == 0 and self._usage_notification_pending:
                self._usage_notification_pending = False
                self._publish_usage()

    def _publish_usage(self) -> None:
        """Publish one immediate cache-accounting update."""
        if self._usage_callback is None:
            return
        try:
            self._usage_callback()
        except Exception:  # pragma: no cover - defensive guard
            logger.exception("Mask cache usage callback failed")
