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
"""Catalog comparison intent and presentation lifecycle for viewers."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from ..catalog.viewer_catalog import ViewerCatalog, ViewerCatalogEntry
from ..rendering.sdk import RenderScene
from ..scene.model import ClipCoordinateSpace, LayerClip
from ..types import ComparisonOrientation, ComparisonState
from .scene_projection import (
    ComparisonSceneProjector,
    comparison_layer_id,
    scene_id,
)


class ViewerComparison(QObject):
    """Own comparison intent and project it through the shared renderer SDK."""

    changed = Signal(object)
    """Emit an immutable ``ComparisonState`` after effective changes."""

    def __init__(
        self,
        catalog: ViewerCatalog,
        set_scene: Callable[[RenderScene | None, bool], bool],
        set_layer_clip: Callable[[uuid.UUID, uuid.UUID, LayerClip], bool],
        parent: QObject | None = None,
    ) -> None:
        """Bind comparison state to one viewer catalog and scene sink."""
        super().__init__(parent)
        self._catalog = catalog
        self._set_scene = set_scene
        self._set_layer_clip = set_layer_clip
        self._projector = ComparisonSceneProjector()
        self._source_id: uuid.UUID | None = None
        self._split_position = 0.5
        self._orientation = ComparisonOrientation.VERTICAL
        self._presented_entries: (
            tuple[ViewerCatalogEntry | None, ViewerCatalogEntry | None] | None
        ) = None
        catalog.selectionChanged.connect(self._handle_selection_changed)
        catalog.changed.connect(self._reconcile_catalog)

    @property
    def active(self) -> bool:
        """Return whether a valid comparison source is enabled."""
        return (
            self._source_id is not None
            and self._catalog.entry(self._source_id) is not None
        )

    def state(self) -> ComparisonState:
        """Return the detached public comparison snapshot."""
        source = (
            None if self._source_id is None else self._catalog.entry(self._source_id)
        )
        return ComparisonState(
            enabled=source is not None,
            source_id=None if source is None else source.entry_id,
            source_path=None if source is None else source.path,
            source_kind=None if source is None else "catalog",
            split_position=self._split_position,
            orientation=self._orientation,
        )

    def show_selection(self, *, fit: bool = True) -> bool:
        """Project the active catalog selection, including comparison state."""
        primary = self._catalog.current
        entries = self._catalog_entries(primary)
        changed = self._set_scene(self._projector.project(*entries), fit)
        self._presented_entries = entries
        if self.active:
            self._present_clip()
        return changed

    def compare_with_next(self) -> bool:
        """Reveal the next catalog source over the active source."""
        entries = self._catalog.entries
        index = self._catalog.current_index
        if len(entries) < 2 or index < 0:
            return False
        self.set_source(entries[(index + 1) % len(entries)].entry_id)
        return True

    def set_source(self, source_id: uuid.UUID) -> None:
        """Enable comparison against one catalog resource."""
        if self._catalog.entry(source_id) is None:
            raise KeyError(f"unknown comparison source: {source_id}")
        if self._catalog.current is None:
            raise RuntimeError("comparison requires an active catalog image")
        if self._source_id == source_id:
            return
        self._source_id = source_id
        self.show_selection(fit=False)
        self.changed.emit(self.state())

    def set_pair(
        self,
        primary_id: uuid.UUID,
        secondary_id: uuid.UUID,
    ) -> None:
        """Atomically select and compare two distinct catalog sources."""
        if primary_id == secondary_id:
            raise ValueError("comparison sources must be distinct")
        if self._catalog.entry(primary_id) is None:
            raise KeyError(f"unknown primary source: {primary_id}")
        if self._catalog.entry(secondary_id) is None:
            raise KeyError(f"unknown comparison source: {secondary_id}")
        pair_changed = (
            self._catalog.current is None
            or self._catalog.current.entry_id != primary_id
            or self._source_id != secondary_id
        )
        if not pair_changed:
            return
        self._source_id = secondary_id
        if not self._catalog.select_entry(primary_id):
            self.show_selection(fit=False)
        self.changed.emit(self.state())

    def set_split(
        self,
        position: float,
        orientation: ComparisonOrientation | str | None = None,
    ) -> None:
        """Set normalized divider position and optional orientation."""
        try:
            normalized = min(1.0, max(0.0, float(position)))
        except (TypeError, ValueError) as exc:
            raise ValueError("comparison split position must be numeric") from exc
        next_orientation = (
            self._orientation
            if orientation is None
            else ComparisonOrientation(orientation)
        )
        if normalized == self._split_position and next_orientation is self._orientation:
            return
        self._split_position = normalized
        self._orientation = next_orientation
        if self.active:
            self._present_clip()
        self.changed.emit(self.state())

    def clear(self) -> None:
        """Disable comparison and preserve the active viewport transform."""
        if self._source_id is None:
            return
        self._source_id = None
        self.show_selection(fit=False)
        self.changed.emit(self.state())

    def abandon(self) -> None:
        """Clear comparison intent before an unrelated host scene replaces it."""
        if self._source_id is None:
            return
        self._source_id = None
        self.changed.emit(self.state())

    def _handle_selection_changed(self, _entry: object) -> None:
        """Present newly selected content without duplicating catalog state."""
        self._present_selection_if_stale()

    def _reconcile_catalog(self) -> None:
        """Reproject replacements or clear a removed comparison source."""
        if self._source_id is not None and self._catalog.entry(self._source_id) is None:
            self._source_id = None
            self.show_selection(fit=False)
            self.changed.emit(self.state())
            return
        if self.active:
            self._present_selection_if_stale()

    def _catalog_entries(
        self,
        primary: ViewerCatalogEntry | None,
    ) -> tuple[ViewerCatalogEntry | None, ViewerCatalogEntry | None]:
        """Return the catalog entries defining the current durable scene."""

        secondary = (
            None if self._source_id is None else self._catalog.entry(self._source_id)
        )
        return primary, secondary

    def _present_selection_if_stale(self) -> None:
        """Project a catalog transition once across its overlapping signals."""

        entries = self._catalog_entries(self._catalog.current)
        if entries != self._presented_entries:
            self.show_selection(fit=False)

    def _present_clip(self) -> None:
        """Apply the live divider clip without replacing durable content."""
        primary = self._catalog.current
        if primary is None or self._source_id is None:
            return
        self._set_layer_clip(
            scene_id(primary.entry_id),
            comparison_layer_id(primary.entry_id, self._source_id),
            self._clip(),
        )

    def _clip(self) -> LayerClip:
        """Return the normalized reveal clip for current comparison state."""
        split = self._split_position
        if self._orientation is ComparisonOrientation.VERTICAL:
            return LayerClip(
                ClipCoordinateSpace.NORMALIZED_SCENE,
                split,
                0.0,
                1.0 - split,
                1.0,
            )
        return LayerClip(
            ClipCoordinateSpace.NORMALIZED_SCENE,
            0.0,
            split,
            1.0,
            1.0 - split,
        )
