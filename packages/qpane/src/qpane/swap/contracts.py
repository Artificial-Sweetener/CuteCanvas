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

"""Typed interfaces for swap-time collaborators.

These runtime-checkable protocols replace reflection-based capability checks in
swap and rendering orchestration. Collaborators must satisfy these contracts at
wire-up time; missing methods or signals are treated as programmer errors.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from PySide6.QtCore import Signal
from PySide6.QtGui import QImage

from ..scene.identity import SceneLayerAssetKey, SceneLayerTileKey, SourceRenderAssetKey


@runtime_checkable
class TilePrefetchManager(Protocol):
    """Capabilities required by swap and rendering when prefetching tiles."""

    tileReady: Signal
    cache_usage_bytes: int
    cache_limit_bytes: int

    def prefetch_tiles(
        self,
        identifiers: Sequence[SceneLayerTileKey],
        source_image: QImage,
        *,
        reason: str = "neighbor",
    ) -> Sequence[SceneLayerTileKey]:
        """Queue tile generation for ``identifiers`` using ``source_image``."""
        ...

    def cancel_prefetch(
        self, identifiers: Sequence[SceneLayerTileKey], *, reason: str
    ) -> None:
        """Request cancellation for prefetches associated with ``identifiers``."""
        ...

    def remove_tiles_for_asset(self, asset_key: SceneLayerAssetKey) -> None:
        """Drop cached tiles and inflight work for ``asset_key``."""
        ...

    def remove_tiles_for_source_asset(
        self, pyramid_asset_key: SourceRenderAssetKey
    ) -> None:
        """Drop cached tiles and inflight work for ``pyramid_asset_key``."""
        ...

    def calculate_grid_dimensions(self, width: int, height: int) -> tuple[int, int]:
        """Return the tile grid dimensions needed to cover ``width`` × ``height``."""
        ...


@runtime_checkable
class PyramidPrefetchManager(Protocol):
    """Capabilities required to prefetch image pyramids."""

    pyramidReady: Signal
    cache_usage_bytes: int
    cache_limit_bytes: int

    def prefetch_pyramid(
        self,
        asset_key: SourceRenderAssetKey,
        image: QImage,
        *,
        reason: str = "prefetch",
    ) -> bool:
        """Begin background pyramid generation for ``asset_key`` when missing."""
        ...

    def cancel_prefetch(
        self, asset_keys: Sequence[SourceRenderAssetKey], *, reason: str = "navigation"
    ) -> Sequence[SourceRenderAssetKey]:
        """Cancel pyramid prefetch for ``asset_keys`` and return cancelled keys."""
        ...


@runtime_checkable
class SceneSourcePrefetcher(Protocol):
    """Feature-neutral source warming used during scene navigation."""

    def has_sources(self, image_id: uuid.UUID) -> bool:
        """Return whether one image scene has prefetchable sources."""
        ...

    def prefetch(
        self,
        image_id: uuid.UUID,
        *,
        reason: str = "navigation",
        scales: Sequence[float] | None = None,
    ) -> bool:
        """Warm feature-owned scene sources for ``image_id``."""
        ...

    def cancel(self, image_id: uuid.UUID | None) -> bool:
        """Cancel queued source prefetch for one or every scene."""
        ...


@runtime_checkable
class SourceWarmupProvider(Protocol):
    """Optional source-specific warmup work coordinated with navigation."""

    def request(
        self,
        image: QImage,
        image_id: uuid.UUID,
        *,
        source_path: Path | None = None,
    ) -> None:
        """Warm products associated with ``image_id``."""
        ...

    def cancel(self, image_id: uuid.UUID) -> bool:
        """Cancel inflight warmup work for ``image_id`` when possible."""
        ...

    def invalidate(self, image_id: uuid.UUID) -> None:
        """Invalidate settled products after source content changes."""
        ...
