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

"""Derived-raster cache for mask scene sources."""

from __future__ import annotations

import logging
import math
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

from ..core import CacheSettings, Config
from ..core.config_features import MaskConfigSlice, require_mask_config
from .mask import MaskAssetStore, MaskLayer
from .mask_undo import MaskHistoryChange
from .rasterizer import MaskRasterizer

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

    def __post_init__(self) -> None:
        """Validate cache-key revision metadata."""
        if self.render_revision < 0:
            raise ValueError("mask render revision must be non-negative")


class MaskRenderCache:
    """Own colorized overlay derivation, caching, and cache diagnostics."""

    def __init__(
        self,
        assets: MaskAssetStore,
        image_to_panel_point: Callable[[QPoint], QPoint | QPointF | None],
        config: Config,
        mask_config: MaskConfigSlice,
        *,
        active_mask_id: Callable[[], uuid.UUID | None],
        async_epoch: Callable[[uuid.UUID], int],
        color_for_mask: Callable[[uuid.UUID | None], QColor],
        render_changed: Callable[[uuid.UUID | None, QRect], None],
        active_properties_changed: Callable[[], None],
    ) -> None:
        """Initialize derived-render state and injected domain lookups."""
        self._assets = assets
        self._image_to_panel_point = image_to_panel_point
        self._config_source = config
        self._mask_config = mask_config
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
        self._prefetched_images: OrderedDict[uuid.UUID, QImage] = OrderedDict()
        self._prefetched_scaled: OrderedDict[uuid.UUID, OrderedDict[float, QImage]] = (
            OrderedDict()
        )
        self._prefetch_limit = 8
        self._async_handler: Callable[[uuid.UUID, MaskLayer], bool] | None = None
        self._async_pending: dict[uuid.UUID, int] = {}
        self._async_threshold_px = 512 * 512
        self._usage_callback: Callable[[], None] | None = None
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
            self.warm(active_id)
            self._render_changed(active_id, QRect())

    def render_revision(self, mask_id: uuid.UUID) -> int:
        """Return a value-derived content and appearance cache identity."""
        layer = self._assets.get_layer(mask_id)
        surface_generation = 0 if layer is None else max(0, layer.surface.generation)
        appearance = int(self._color_for_mask(mask_id).rgba())
        border_enabled = int(bool(self._mask_config.mask_border_enabled))
        return (
            surface_generation
            | (max(0, self._async_epoch(mask_id)) << 32)
            | (appearance << 64)
            | (border_enabled << 96)
        )

    def preview_stride(self, mask_id: uuid.UUID, viewport_zoom: float) -> int:
        """Return a preview stride satisfying the active render resolution."""
        required_scale = max(
            max(1e-6, float(viewport_zoom)),
            self._requested_scales.get(mask_id, 1.0),
        )
        return 1 if required_scale >= 1.0 else max(1, math.floor(1 / required_scale))

    def discard_source(self, mask_id: uuid.UUID) -> None:
        """Forget render state associated with a deleted source."""
        self.cancel_async(mask_id)
        self._requested_scales.pop(mask_id, None)
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
        return max(0, int(settings.resolved_consumer_budgets_bytes().get("masks", 0)))

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
        image = layer.surface.snapshot_qimage()
        if image.isNull():
            return None
        resolved_id = layer.mask_id if mask_id is None else mask_id
        return self.colorize_image(
            image,
            self._color_for_mask(resolved_id),
            mask_id=resolved_id,
            source=source,
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

    def notify_color_changed(self, mask_id: uuid.UUID) -> None:
        """Invalidate derived rasters after a tint change."""
        self.invalidate(mask_id)
        self.warm(mask_id)
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
        self._forget_prefetched(mask_id)
        for key in list(self._mask_index.get(mask_id, ())):
            self._drop(key, reason=reason)

    def invalidate_layer(self, layer: MaskLayer | None) -> None:
        """Invalidate the layer's derived rasters."""
        if layer is not None:
            self.invalidate(layer.mask_id)

    def warm(self, mask_id: uuid.UUID | None) -> None:
        """Generate the base cached raster for a source when present."""
        if mask_id is None:
            return
        layer = self._assets.get_layer(mask_id)
        if layer is not None:
            self.get(layer)

    def get(self, layer: MaskLayer, *, scale: float | None = None) -> QPixmap | None:
        """Return a colorized cached raster for a layer."""
        return self._get(layer, scale=scale)

    def get_by_id(
        self, mask_id: uuid.UUID, *, scale: float | None = None
    ) -> QPixmap | None:
        """Return a cached raster for a source id."""
        layer = self._assets.get_layer(mask_id)
        if layer is None:
            return None
        scale_key = self.normalize_scale(scale)
        self._requested_scales[mask_id] = 1.0 if scale_key is None else scale_key
        return self._get(layer, scale=scale)

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
        base_key = self._key(mask_id, None)
        base_pixmap = self._cache.get(base_key)
        if preview_stride is not None and preview_stride > 1:
            if base_pixmap is not None:
                self._drop(base_key, reason="decimated_preview")
            base_pixmap = None
        elif base_pixmap is None:
            base_pixmap = self._get(layer)
        self._forget_prefetched(mask_id)
        region = sub_mask_image or layer.mask_image.copy(dirty_rect)
        colorized = colorized_image or self.colorize_image(
            region,
            self._color_for_mask(mask_id),
            mask_id=mask_id,
            source="snippet_provisional" if preview_provisional else "snippet",
        )
        snippet = QPixmap.fromImage(colorized)
        if base_pixmap is not None and not base_pixmap.isNull():
            painter = QPainter(base_pixmap)
            painter.setCompositionMode(QPainter.CompositionMode_Source)
            painter.drawPixmap(dirty_rect.topLeft(), snippet)
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
            destination = QRect(
                QPoint(
                    round(dirty_rect.left() * scale_key),
                    round(dirty_rect.top() * scale_key),
                ),
                self.target_scaled_size(dirty_rect.size(), scale_key),
            )
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
        mask_rect = layer.mask_image.rect()
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
            image = self.colorize_image(
                layer.mask_image.copy(rect),
                self._color_for_mask(layer.mask_id),
                mask_id=layer.mask_id,
                source="history_snippet",
            )
            snippet = QPixmap.fromImage(image)
            for scale_key, (_key, cached, _size) in latest.items():
                painter = QPainter(cached)
                painter.setCompositionMode(QPainter.CompositionMode_Source)
                if scale_key is None:
                    painter.drawPixmap(rect.topLeft(), snippet)
                else:
                    painter.setRenderHint(
                        QPainter.RenderHint.SmoothPixmapTransform, True
                    )
                    destination = QRect(
                        QPoint(
                            round(rect.left() * scale_key),
                            round(rect.top() * scale_key),
                        ),
                        self.target_scaled_size(rect.size(), scale_key),
                    )
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

    def _key(self, mask_id: uuid.UUID, scale_key: float | None) -> MaskRenderCacheKey:
        """Build one stable cache key."""
        return MaskRenderCacheKey(mask_id, self.render_revision(mask_id), scale_key)

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
        if scale_key is not None:
            stored = self._prefetched_scaled.get(mask_id, {}).get(scale_key)
            if stored is not None and not stored.isNull():
                self._hits += 1
                result = QPixmap.fromImage(stored)
                self._insert(key, result, mask_id=mask_id)
                return result
        image = layer.mask_image
        if image.isNull():
            return None
        if scale_key is None:
            stored = self._prefetched_images.get(mask_id)
            if stored is not None and not stored.isNull():
                self._hits += 1
                result = QPixmap.fromImage(stored)
                self._insert(key, result, mask_id=mask_id)
                return result
            elif (
                self._async_handler is not None
                and image.width() * image.height() > self._async_threshold_px
                and self._async_pending.get(mask_id) != key.render_revision
            ):
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
        else:
            base = self._cache.get(self._key(mask_id, None))
            if base is not None:
                result = base.scaled(self.target_scaled_size(base.size(), scale_key))
            else:
                scaled = image.scaled(self.target_scaled_size(image.size(), scale_key))
                if scaled.format() != QImage.Format.Format_Grayscale8:
                    scaled = scaled.convertToFormat(QImage.Format.Format_Grayscale8)
                result = self._colorize_pixmap(scaled, mask_id, "scaled_cache_miss")
        self._misses += 1
        self._insert(key, result, mask_id=mask_id)
        return result

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
        top_left = self._image_to_panel_point(image_rect.topLeft())
        bottom_right = self._image_to_panel_point(image_rect.bottomRight())
        if top_left is None or bottom_right is None:
            self._render_changed(mask_id, QRect())
            return
        panel_rect = QRectF(top_left, bottom_right).normalized().adjusted(-2, -2, 2, 2)
        self._render_changed(mask_id, panel_rect.toRect())

    def _notify_usage(self) -> None:
        """Notify cache coordination after an accounting change."""
        if self._usage_callback is None:
            return
        try:
            self._usage_callback()
        except Exception:  # pragma: no cover - defensive guard
            logger.exception("Mask cache usage callback failed")
