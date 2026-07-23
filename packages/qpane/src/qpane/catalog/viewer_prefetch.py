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
"""Bounded neighboring-source prefetch for viewer catalog navigation."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtGui import QImage

from ..core.config import Config
from ..rendering.pyramid import PyramidManager
from ..scene.identity import SourceRenderAssetKey, source_render_asset_key
from ..types import DiagnosticRecord
from .viewer_catalog import ViewerCatalog, ViewerCatalogEntry

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ViewerPrefetchSnapshot:
    """Describe viewer-owned neighboring pyramid work."""

    pending: int
    scheduled: int
    completed: int
    cancelled: int


class ViewerPrefetch:
    """Warm neighboring raster pyramids and cancel obsolete navigation work."""

    def __init__(
        self,
        catalog: ViewerCatalog,
        pyramids: PyramidManager,
        config: Config,
        dirty: Callable[[], None],
    ) -> None:
        """Bind one catalog to rendering-owned pyramid products."""
        self._catalog = catalog
        self._pyramids = pyramids
        self._dirty = dirty
        self._depth = 0
        self._pending: set[SourceRenderAssetKey] = set()
        self._scheduled = 0
        self._completed = 0
        self._cancelled = 0
        self.apply_config(config)
        catalog.selectionChanged.connect(self._selection_changed)
        catalog.changed.connect(self._catalog_changed)
        pyramids.pyramidReady.connect(self._pyramid_ready)

    def apply_config(self, config: Config) -> None:
        """Apply the catalog pyramid-prefetch depth from ``config``."""
        raw_depth = config.cache.prefetch.pyramids
        try:
            self._depth = int(raw_depth)
        except (TypeError, ValueError):
            self._depth = -1
        if self._depth == 0:
            self._cancel_obsolete(set(), reason="config-update")
        elif self._catalog.current is not None:
            self._schedule_neighbors()

    def snapshot(self) -> ViewerPrefetchSnapshot:
        """Return immutable counters for diagnostics and tests."""
        return ViewerPrefetchSnapshot(
            pending=len(self._pending),
            scheduled=self._scheduled,
            completed=self._completed,
            cancelled=self._cancelled,
        )

    def diagnostics(self, _pane: object) -> tuple[DiagnosticRecord, ...]:
        """Return one concise live catalog-prefetch record."""
        state = self.snapshot()
        return (
            DiagnosticRecord(
                "Catalog Prefetch",
                (
                    f"pending={state.pending} | scheduled={state.scheduled} | "
                    f"completed={state.completed} | cancelled={state.cancelled}"
                ),
            ),
        )

    def shutdown(self) -> None:
        """Cancel every tracked speculative pyramid request."""
        self._cancel_obsolete(set(), reason="shutdown")

    def _selection_changed(self, _entry: ViewerCatalogEntry | None) -> None:
        """Restart bounded speculative work around the new selection."""
        self._schedule_neighbors()

    def _catalog_changed(self) -> None:
        """Drop removed resources from pending work and refresh candidates."""
        valid = {self._key(entry) for entry in self._catalog.entries}
        self._cancel_obsolete(self._pending & valid, reason="catalog-change")

    def _schedule_neighbors(self) -> None:
        """Schedule candidate pyramids while preserving still-useful work."""
        candidates = self._neighbor_entries()
        candidate_keys = {self._key(entry) for entry in candidates}
        self._cancel_obsolete(candidate_keys, reason="navigation")
        for entry in candidates:
            key = self._key(entry)
            if key in self._pending:
                continue
            image = entry.source.provider.image(None)
            if image is None or not isinstance(image, QImage) or image.isNull():
                continue
            try:
                scheduled = self._pyramids.prefetch_pyramid(
                    key,
                    image,
                    reason="viewer-neighbor",
                )
            except Exception:
                logger.exception("Catalog pyramid prefetch failed for %s", key)
                continue
            if scheduled:
                self._pending.add(key)
                self._scheduled += 1
        self._dirty()

    def _neighbor_entries(self) -> tuple[ViewerCatalogEntry, ...]:
        """Return alternating next/previous entries within configured depth."""
        entries = self._catalog.entries
        current_index = self._catalog.current_index
        if self._depth == 0 or current_index < 0 or len(entries) < 2:
            return ()
        limit = (
            len(entries) - 1 if self._depth < 0 else min(self._depth, len(entries) - 1)
        )
        candidates: list[ViewerCatalogEntry] = []
        seen = {current_index}
        distance = 1
        while len(candidates) < limit and len(seen) < len(entries):
            for index in (
                (current_index + distance) % len(entries),
                (current_index - distance) % len(entries),
            ):
                if index in seen:
                    continue
                seen.add(index)
                candidates.append(entries[index])
                if len(candidates) >= limit:
                    break
            distance += 1
        return tuple(candidates)

    def _cancel_obsolete(
        self,
        keep: set[SourceRenderAssetKey],
        *,
        reason: str,
    ) -> None:
        """Cancel tracked work outside ``keep`` and repair counters."""
        obsolete = tuple(self._pending - keep)
        if obsolete:
            try:
                cancelled = self._pyramids.cancel_prefetch(obsolete, reason=reason)
            except Exception:
                logger.exception("Catalog pyramid cancellation failed")
                cancelled = []
            self._cancelled += len(cancelled)
        self._pending.intersection_update(keep)
        self._dirty()

    def _pyramid_ready(self, key: SourceRenderAssetKey) -> None:
        """Retire one completed speculative product."""
        if key not in self._pending:
            return
        self._pending.remove(key)
        self._completed += 1
        self._dirty()

    @staticmethod
    def _key(entry: ViewerCatalogEntry) -> SourceRenderAssetKey:
        """Return reusable pyramid identity for one public raster source."""
        source = entry.source
        return source_render_asset_key(
            source_id=source.source_id,
            source_kind=source.source_kind,
            revision=source.revision,
            source_path=source.path,
        )
