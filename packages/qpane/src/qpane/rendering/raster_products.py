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
"""Own revision-aware derived raster products shared by every raster source."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from typing import Protocol

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from ..scene.identity import SourceRenderAssetKey


class RasterPyramidProducts(Protocol):
    """Expose the pyramid operations needed by raster-product selection."""

    def pyramid_for_asset(self, asset_key: SourceRenderAssetKey) -> object | None:
        """Return retained product state for ``asset_key`` when present."""
        ...

    def generate_pyramid_for_asset(
        self,
        asset_key: SourceRenderAssetKey,
        image: QImage,
    ) -> None:
        """Request derived levels for one immutable source revision."""
        ...

    def get_best_fit_image_for_asset(
        self,
        asset_key: SourceRenderAssetKey,
        target_width: float,
    ) -> QImage | None:
        """Return the closest available image product for ``target_width``."""
        ...

    def remove_pyramid(self, asset_key: SourceRenderAssetKey) -> None:
        """Discard every derived level for one obsolete source revision."""
        ...


class RasterTileProducts(Protocol):
    """Expose source-oriented tile invalidation."""

    def remove_tiles_for_source_asset(
        self,
        asset_key: SourceRenderAssetKey,
    ) -> None:
        """Discard every tile derived from ``asset_key``."""
        ...


class RasterRenderProductStore:
    """Select and invalidate shared raster pyramids independently of source kind."""

    def __init__(
        self,
        pyramids: RasterPyramidProducts,
        tiles: RasterTileProducts,
    ) -> None:
        """Bind the shared derived-product managers."""
        self._pyramids = pyramids
        self._tiles = tiles
        self._current_revision: dict[tuple[str, object], SourceRenderAssetKey] = {}
        self._preview_products: OrderedDict[
            tuple[SourceRenderAssetKey, int], QImage
        ] = OrderedDict()
        self._preview_usage_bytes = 0
        self._preview_budget_bytes = 64 * 1024 * 1024
        self._usage_changed: Callable[[int], None] | None = None

    @property
    def usage_bytes(self) -> int:
        """Return bytes retained by bounded pending-pyramid previews."""
        return self._preview_usage_bytes

    def set_usage_changed(self, callback: Callable[[int], None] | None) -> None:
        """Install the shared-cache accounting callback."""
        self._usage_changed = callback
        self._notify_usage()

    def set_budget(self, budget_bytes: int) -> None:
        """Set the byte budget for pending-pyramid preview products."""
        self._preview_budget_bytes = max(0, int(budget_bytes))
        self.trim_to(self._preview_budget_bytes)

    def trim_to(self, target_bytes: int) -> None:
        """Evict least-recent previews until usage meets ``target_bytes``."""
        target = max(0, int(target_bytes))
        changed = False
        while self._preview_products and self._preview_usage_bytes > target:
            _key, image = self._preview_products.popitem(last=False)
            self._preview_usage_bytes -= image.sizeInBytes()
            changed = True
        if changed:
            self._notify_usage()

    def best_fit_image(
        self,
        *,
        asset_key: SourceRenderAssetKey,
        full_image: QImage,
        target_width: float,
    ) -> QImage:
        """Return the best available product and lazily request missing levels."""
        self._advance_source_revision(asset_key)
        if self._pyramids.pyramid_for_asset(asset_key) is None:
            self._pyramids.generate_pyramid_for_asset(asset_key, full_image)
        product = self._pyramids.get_best_fit_image_for_asset(asset_key, target_width)
        selected = full_image if product is None or product.isNull() else product
        preview_width = self._preview_width(full_image.width(), target_width)
        if selected.width() > preview_width * 2:
            return self._pending_preview(
                asset_key=asset_key,
                full_image=full_image,
                width=preview_width,
            )
        self._discard_previews(asset_key)
        return selected

    def sampled_image(
        self,
        *,
        asset_key: SourceRenderAssetKey,
        source_width: int,
        target_width: float,
        producer: Callable[[float], QImage | None],
    ) -> QImage | None:
        """Return one cached display sample from a sparse source-owned producer."""
        self._advance_source_revision(asset_key)
        width = self._preview_width(source_width, target_width)
        cache_key = (asset_key, width)
        cached = self._preview_products.get(cache_key)
        if cached is not None:
            self._preview_products.move_to_end(cache_key)
            return cached
        scale = width / max(1, int(source_width))
        sampled = producer(scale)
        if sampled is None or sampled.isNull():
            return None
        sampled_bytes = sampled.sizeInBytes()
        if sampled_bytes <= self._preview_budget_bytes:
            self._preview_products[cache_key] = sampled
            self._preview_usage_bytes += sampled_bytes
            self.trim_to(self._preview_budget_bytes)
            self._notify_usage()
        return sampled

    def forget(self, asset_key: SourceRenderAssetKey) -> None:
        """Discard products and revision bookkeeping for one exact source revision."""
        self._pyramids.remove_pyramid(asset_key)
        self._tiles.remove_tiles_for_source_asset(asset_key)
        self._discard_previews(asset_key)
        identity = self._source_identity(asset_key)
        if self._current_revision.get(identity) == asset_key:
            self._current_revision.pop(identity, None)

    def _advance_source_revision(self, asset_key: SourceRenderAssetKey) -> None:
        """Drop stale products before selecting a newly observed source revision."""
        identity = self._source_identity(asset_key)
        previous = self._current_revision.get(identity)
        if previous is not None and previous != asset_key:
            self._pyramids.remove_pyramid(previous)
            self._tiles.remove_tiles_for_source_asset(previous)
            self._discard_previews(previous)
        self._current_revision[identity] = asset_key

    def _pending_preview(
        self,
        *,
        asset_key: SourceRenderAssetKey,
        full_image: QImage,
        width: int,
    ) -> QImage:
        """Return one reusable display-bounded product while refinement runs."""
        cache_key = (asset_key, width)
        cached = self._preview_products.get(cache_key)
        if cached is not None:
            self._preview_products.move_to_end(cache_key)
            return cached
        height = max(1, round(full_image.height() * width / full_image.width()))
        preview = full_image.scaled(
            width,
            height,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        preview_bytes = preview.sizeInBytes()
        if preview_bytes <= self._preview_budget_bytes:
            self._preview_products[cache_key] = preview
            self._preview_usage_bytes += preview_bytes
            self.trim_to(self._preview_budget_bytes)
            self._notify_usage()
        return preview

    def _discard_previews(self, asset_key: SourceRenderAssetKey) -> None:
        """Discard transient previews for one exact source revision."""
        keys = tuple(key for key in self._preview_products if key[0] == asset_key)
        if not keys:
            return
        for key in keys:
            self._preview_usage_bytes -= self._preview_products.pop(key).sizeInBytes()
        self._notify_usage()

    @staticmethod
    def _preview_width(full_width: int, target_width: float) -> int:
        """Return a power-of-two display width bounded by the source width."""
        desired = max(1, min(full_width, round(max(1.0, target_width))))
        bucket = 1 << (desired - 1).bit_length()
        return min(full_width, bucket)

    def _notify_usage(self) -> None:
        """Publish preview-cache usage when shared coordination is installed."""
        if self._usage_changed is not None:
            self._usage_changed(self._preview_usage_bytes)

    @staticmethod
    def _source_identity(asset_key: SourceRenderAssetKey) -> tuple[str, object]:
        """Return revision-independent identity for one authoritative source."""
        return asset_key.source_kind, asset_key.source_id
