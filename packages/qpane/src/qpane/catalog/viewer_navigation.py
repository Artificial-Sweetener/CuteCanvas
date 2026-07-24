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

from PySide6.QtCore import QRectF, QSizeF
from PySide6.QtWidgets import QWidget

from ..inspection import (
    InspectionStateStore,
    InspectionTarget,
    InspectionViewState,
    InspectionZoomMode,
    capture_inspection,
    project_inspection,
)
from ..rendering.viewport import Viewport, ViewportZoomMode
from ..types import LinkedGroup
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
        self._inspection = InspectionStateStore()
        self._known_ids: set[uuid.UUID] = set()
        catalog.selectionChanging.connect(self._capture_outgoing)
        catalog.selectionChanged.connect(self._restore_incoming)
        catalog.changed.connect(self._reconcile_catalog)

    def groups(self) -> tuple[LinkedGroup, ...]:
        """Return immutable linked-image group records."""
        return self._inspection.groups()

    def set_groups(self, groups: tuple[LinkedGroup, ...]) -> None:
        """Replace linked-image groups after validating catalog membership."""
        known = {entry.entry_id for entry in self._catalog.entries}
        for group in groups:
            unknown = tuple(member for member in group.members if member not in known)
            if unknown:
                raise KeyError(f"linked image is not in the catalog: {unknown[0]}")
        self._inspection.replace_groups(groups)

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
        self._inspection.discard(entry_id)

    def clear(self) -> None:
        """Clear all stored individual and linked viewport state."""
        self._inspection.clear()

    def _reconcile_catalog(self) -> None:
        """Discard viewport state for resources removed from the catalog."""
        current_ids = {entry.entry_id for entry in self._catalog.entries}
        for removed_id in self._known_ids - current_ids:
            self._inspection.discard(removed_id)
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
            self._inspection.update(outgoing.entry_id, state)

    def _restore_incoming(self, incoming: ViewerCatalogEntry | None) -> None:
        """Restore a known resource transform or fit a first-time resource."""
        if incoming is None:
            return
        state = self._inspection.state_for(incoming.entry_id)
        if state is None or state.zoom_mode is InspectionZoomMode.FIT:
            self._viewport.setZoomFit()
            return
        self._restore(incoming, state)

    def _capture(
        self,
        entry: ViewerCatalogEntry,
    ) -> InspectionViewState | None:
        """Return source-size-independent viewport center and visible region."""
        zoom = float(self._viewport.zoom)
        if entry.size.width() <= 0 or entry.size.height() <= 0 or zoom <= 0.0:
            return None
        return capture_inspection(
            self._target(entry),
            self._physical_viewport_size(),
            zoom=zoom,
            pan=self._viewport.pan,
            zoom_mode=self._inspection_zoom_mode(self._viewport.get_zoom_mode()),
        )

    def _restore(
        self,
        entry: ViewerCatalogEntry,
        state: InspectionViewState,
    ) -> None:
        """Apply a normalized viewport state to one catalog resource."""
        projected = project_inspection(
            self._target(entry),
            self._physical_viewport_size(),
            state,
        )
        self._viewport.zoom_mode = ViewportZoomMode.CUSTOM
        self._viewport.setZoomAndPan(projected.zoom, projected.pan)
        if projected.zoom_mode is InspectionZoomMode.ONE_TO_ONE:
            self._viewport.zoom_mode = ViewportZoomMode.ONE_TO_ONE

    def _physical_viewport_size(self) -> QSizeF:
        """Return current widget dimensions in physical device pixels."""
        dpr = self._widget.devicePixelRatioF()
        return QSizeF(self._widget.width() * dpr, self._widget.height() * dpr)

    @staticmethod
    def _target(entry: ViewerCatalogEntry) -> InspectionTarget:
        """Adapt one catalog entry to the generic inspection contract."""
        return InspectionTarget(
            target_id=entry.entry_id,
            bounds=QRectF(
                0.0,
                0.0,
                float(entry.size.width()),
                float(entry.size.height()),
            ),
        )

    @staticmethod
    def _inspection_zoom_mode(mode: ViewportZoomMode) -> InspectionZoomMode:
        """Convert internal viewport mode to a public inspection mode."""
        if mode is ViewportZoomMode.FIT:
            return InspectionZoomMode.FIT
        if mode is ViewportZoomMode.ONE_TO_ONE:
            return InspectionZoomMode.ONE_TO_ONE
        return InspectionZoomMode.CUSTOM
