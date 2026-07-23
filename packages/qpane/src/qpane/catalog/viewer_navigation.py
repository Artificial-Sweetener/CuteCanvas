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
"""Per-resource viewport persistence and linked navigation policy."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QWidget

from ..rendering.coordinates import NormalizedViewState
from ..rendering.viewport import Viewport, ViewportZoomMode
from ..types import LinkedGroup
from .link import LinkManager
from .viewer_catalog import ViewerCatalog, ViewerCatalogEntry


class ViewerNavigation:
    """Preserve independent or linked pan/zoom state across catalog swaps."""

    def __init__(
        self,
        catalog: ViewerCatalog,
        viewport: Viewport,
        widget: QWidget,
    ) -> None:
        """Bind catalog selection transitions to one viewport."""
        self._catalog = catalog
        self._viewport = viewport
        self._widget = widget
        self._links = LinkManager()
        self._known_ids: set[uuid.UUID] = set()
        catalog.selectionChanging.connect(self._capture_outgoing)
        catalog.selectionChanged.connect(self._restore_incoming)
        catalog.changed.connect(self._reconcile_catalog)

    def groups(self) -> tuple[LinkedGroup, ...]:
        """Return immutable linked-image group records."""
        return self._links.getGroupRecords()

    def set_groups(self, groups: tuple[LinkedGroup, ...]) -> None:
        """Replace linked-image groups after validating catalog membership."""
        known = {entry.entry_id for entry in self._catalog.entries}
        for group in groups:
            unknown = tuple(member for member in group.members if member not in known)
            if unknown:
                raise KeyError(f"linked image is not in the catalog: {unknown[0]}")
        self._links.setGroups(groups)

    def set_all_linked(self, enabled: bool) -> None:
        """Link all catalog images or clear every linked group."""
        entries = self._catalog.entries
        if enabled and len(entries) >= 2:
            members = tuple(entry.entry_id for entry in entries)
            existing = next(
                (
                    group
                    for group in self.groups()
                    if set(group.members) == set(members)
                ),
                None,
            )
            group_id = existing.group_id if existing is not None else uuid.uuid4()
            self.set_groups((LinkedGroup(group_id=group_id, members=members),))
            return
        self.set_groups(())

    def discard(self, entry_id: uuid.UUID) -> None:
        """Remove one resource from stored individual and linked view state."""
        self._links.handleImageRemoved(entry_id)

    def clear(self) -> None:
        """Clear all stored individual and linked viewport state."""
        self._links.clear()

    def _reconcile_catalog(self) -> None:
        """Discard viewport state for resources removed from the catalog."""
        current_ids = {entry.entry_id for entry in self._catalog.entries}
        for removed_id in self._known_ids - current_ids:
            self._links.handleImageRemoved(removed_id)
        self._known_ids = current_ids

    def _capture_outgoing(
        self,
        outgoing: ViewerCatalogEntry | None,
        _incoming: ViewerCatalogEntry | None,
    ) -> None:
        """Persist the outgoing resource before scene geometry changes."""
        if outgoing is None:
            return
        state = self._capture(outgoing)
        if state is not None:
            self._links.updateViewState(outgoing.entry_id, state)

    def _restore_incoming(self, incoming: ViewerCatalogEntry | None) -> None:
        """Restore a known resource transform or fit a first-time resource."""
        if incoming is None:
            return
        state = self._links.getViewState(incoming.entry_id)
        if state is None or state.zoom_mode is ViewportZoomMode.FIT:
            self._viewport.setZoomFit()
            return
        self._restore(incoming, state)

    def _capture(
        self,
        entry: ViewerCatalogEntry,
    ) -> NormalizedViewState | None:
        """Return source-size-independent viewport center and visible width."""
        width = entry.size.width()
        height = entry.size.height()
        zoom = float(self._viewport.zoom)
        if width <= 0 or height <= 0 or zoom <= 0.0:
            return None
        pan = self._viewport.pan
        physical_width = self._widget.width() * self._widget.devicePixelRatioF()
        return NormalizedViewState(
            center_x=0.5 - pan.x() / (width * zoom),
            center_y=0.5 - pan.y() / (height * zoom),
            zoom_frac=physical_width / (width * zoom),
            zoom_mode=self._viewport.get_zoom_mode(),
        )

    def _restore(
        self,
        entry: ViewerCatalogEntry,
        state: NormalizedViewState,
    ) -> None:
        """Apply a normalized viewport state to one catalog resource."""
        width = entry.size.width()
        height = entry.size.height()
        physical_width = self._widget.width() * self._widget.devicePixelRatioF()
        if width <= 0 or height <= 0 or state.zoom_frac <= 0.0:
            self._viewport.setZoomFit()
            return
        zoom = physical_width / (width * state.zoom_frac)
        pan = QPointF(
            (0.5 - state.center_x) * width * zoom,
            (0.5 - state.center_y) * height * zoom,
        )
        self._viewport.zoom_mode = ViewportZoomMode.CUSTOM
        self._viewport.setZoomAndPan(zoom, pan)
        if state.zoom_mode is ViewportZoomMode.ONE_TO_ONE:
            self._viewport.zoom_mode = ViewportZoomMode.ONE_TO_ONE
