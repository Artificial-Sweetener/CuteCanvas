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
"""Ordered reusable image resources for QPane's viewer facade."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Signal
from PySide6.QtGui import QImage

from ..rendering.sdk import RasterSource


@dataclass(frozen=True, slots=True)
class ViewerCatalogEntry:
    """Describe one named, reusable raster source in viewer order."""

    source: RasterSource
    label: str
    path: Path | None = None

    def __post_init__(self) -> None:
        """Normalize host metadata without copying source pixels."""
        label = str(self.label).strip()
        if not label:
            raise ValueError("catalog entry label must not be empty")
        object.__setattr__(self, "label", label)
        object.__setattr__(
            self,
            "path",
            self.source.path if self.path is None else Path(self.path),
        )

    @property
    def entry_id(self) -> uuid.UUID:
        """Return the stable raster-resource identity."""
        return self.source.source_id

    @property
    def size(self) -> QSize:
        """Return detached intrinsic pixel dimensions."""
        return self.source.size


class ViewerCatalog(QObject):
    """Own ordered viewer resources and one optional active selection."""

    changed = Signal()
    """Emit after resource order or metadata changes."""
    selectionChanging = Signal(object, object)
    """Emit outgoing and incoming entries before active selection changes."""
    selectionChanged = Signal(object)
    """Emit the selected ``ViewerCatalogEntry`` or ``None``."""
    resourcesInvalidated = Signal(object)
    """Emit raster sources whose derived render products must be discarded."""

    def __init__(self, parent: QObject | None = None) -> None:
        """Create an empty catalog with no selected resource."""
        super().__init__(parent)
        self._entries: list[ViewerCatalogEntry] = []
        self._current_index = -1

    @property
    def entries(self) -> tuple[ViewerCatalogEntry, ...]:
        """Return the ordered immutable catalog snapshot."""
        return tuple(self._entries)

    @property
    def current_index(self) -> int:
        """Return the active index, or ``-1`` when empty or deselected."""
        return self._current_index

    @property
    def current(self) -> ViewerCatalogEntry | None:
        """Return the active entry when one is selected."""
        if not 0 <= self._current_index < len(self._entries):
            return None
        return self._entries[self._current_index]

    def add_image(
        self,
        image: QImage,
        *,
        label: str,
        path: Path | None = None,
        source_id: uuid.UUID | None = None,
        select: bool = True,
    ) -> ViewerCatalogEntry:
        """Create one reusable source, append it, and optionally select it.

        Args:
            image: Non-null image retained through implicit QImage sharing.
            label: Human-readable resource name.
            path: Optional source path used for identity and presentation.
            source_id: Optional stable identity supplied by the host.
            select: Whether the added resource becomes current.

        Returns:
            The immutable catalog entry created for the image.
        """
        source = RasterSource.from_image(
            image,
            source_id=source_id,
            path=path,
        )
        return self.add_source(source, label=label, path=path, select=select)

    def add_source(
        self,
        source: RasterSource,
        *,
        label: str,
        path: Path | None = None,
        select: bool = True,
    ) -> ViewerCatalogEntry:
        """Append an existing raster source without duplicating its pixels."""
        if any(entry.entry_id == source.source_id for entry in self._entries):
            raise ValueError(f"catalog source already exists: {source.source_id}")
        entry = ViewerCatalogEntry(source=source, label=label, path=path)
        self._entries.append(entry)
        self.changed.emit()
        if select:
            self.select(len(self._entries) - 1)
        return entry

    def replace_source(
        self,
        source: RasterSource,
        *,
        label: str | None = None,
        path: Path | None = None,
    ) -> tuple[ViewerCatalogEntry, ViewerCatalogEntry]:
        """Replace one resource in place while preserving ordering and selection.

        Raises:
            KeyError: If the source identity is not in the catalog.
        """
        index = self.index_of(source.source_id)
        if index < 0:
            raise KeyError(f"unknown catalog source: {source.source_id}")
        previous = self._entries[index]
        replacement = ViewerCatalogEntry(
            source=source,
            label=previous.label if label is None else label,
            path=path,
        )
        if index == self._current_index:
            self.selectionChanging.emit(previous, replacement)
        self._entries[index] = replacement
        self.changed.emit()
        if index == self._current_index:
            self.selectionChanged.emit(replacement)
        self.resourcesInvalidated.emit((previous.source,))
        return previous, replacement

    def replace_all(
        self,
        entries: tuple[ViewerCatalogEntry, ...],
        current_id: uuid.UUID,
    ) -> None:
        """Atomically replace resources and select one supplied identity.

        Raises:
            ValueError: If entries are empty or contain duplicate identities.
            KeyError: If ``current_id`` is not among ``entries``.
        """
        if not entries:
            raise ValueError("catalog entries must not be empty")
        ids = tuple(entry.entry_id for entry in entries)
        if len(set(ids)) != len(ids):
            raise ValueError("catalog entries must have unique source identities")
        try:
            current_index = ids.index(current_id)
        except ValueError as exc:
            raise KeyError(f"unknown current catalog source: {current_id}") from exc
        previous_entries = tuple(self._entries)
        previous = self.current
        selected = entries[current_index]
        if previous != selected:
            self.selectionChanging.emit(previous, selected)
        self._entries = list(entries)
        self._current_index = current_index
        self.changed.emit()
        if previous != selected:
            self.selectionChanged.emit(selected)
        invalidated = tuple(
            entry.source
            for entry in previous_entries
            if not any(entry.source is current.source for current in entries)
        )
        if invalidated:
            self.resourcesInvalidated.emit(invalidated)

    def entry(self, entry_id: uuid.UUID) -> ViewerCatalogEntry | None:
        """Return the entry with ``entry_id`` when present."""
        return next(
            (entry for entry in self._entries if entry.entry_id == entry_id),
            None,
        )

    def index_of(self, entry_id: uuid.UUID) -> int:
        """Return the index for ``entry_id``, or ``-1`` when absent."""
        return next(
            (
                index
                for index, entry in enumerate(self._entries)
                if entry.entry_id == entry_id
            ),
            -1,
        )

    def select(self, index: int) -> bool:
        """Select an existing index and publish the immutable entry.

        Raises:
            IndexError: If ``index`` does not identify a catalog entry.
        """
        if not 0 <= index < len(self._entries):
            raise IndexError("catalog index is out of range")
        if index == self._current_index:
            return False
        previous = self.current
        selected = self._entries[index]
        self.selectionChanging.emit(previous, selected)
        self._current_index = index
        self.selectionChanged.emit(selected)
        self.changed.emit()
        return True

    def select_entry(self, entry_id: uuid.UUID) -> bool:
        """Select a resource by stable identity.

        Raises:
            KeyError: If ``entry_id`` is not in the catalog.
        """
        index = self.index_of(entry_id)
        if index < 0:
            raise KeyError(f"unknown catalog source: {entry_id}")
        return self.select(index)

    def step(self, offset: int) -> bool:
        """Wrap the active selection by ``offset`` entries."""
        if not self._entries:
            return False
        base = max(self._current_index, 0)
        return self.select((base + int(offset)) % len(self._entries))

    def deselect(self) -> bool:
        """Clear active selection while retaining ordered resources."""
        previous = self.current
        if previous is None:
            return False
        self.selectionChanging.emit(previous, None)
        self._current_index = -1
        self.selectionChanged.emit(None)
        self.changed.emit()
        return True

    def remove_current(self) -> ViewerCatalogEntry | None:
        """Remove the active entry and select its nearest neighbor."""
        current = self.current
        if current is None:
            return None
        return self.remove(current.entry_id)

    def remove(self, entry_id: uuid.UUID) -> ViewerCatalogEntry:
        """Remove one resource and repair selection deterministically.

        Raises:
            KeyError: If ``entry_id`` is not in the catalog.
        """
        index = self.index_of(entry_id)
        if index < 0:
            raise KeyError(f"unknown catalog source: {entry_id}")
        removed = self._entries[index]
        previous_index = self._current_index
        next_entries = self._entries[:index] + self._entries[index + 1 :]
        if not next_entries:
            next_index = -1
        elif previous_index == index:
            next_index = min(index, len(next_entries) - 1)
        elif index < previous_index:
            next_index = previous_index - 1
        else:
            next_index = previous_index
        selection_changed = previous_index == index or not next_entries
        next_entry = next_entries[next_index] if next_index >= 0 else None
        if selection_changed:
            self.selectionChanging.emit(self.current, next_entry)
        self._entries = next_entries
        self._current_index = next_index
        self.changed.emit()
        if selection_changed:
            self.selectionChanged.emit(self.current)
        self.resourcesInvalidated.emit((removed.source,))
        return removed

    def clear(self) -> None:
        """Remove every resource and clear the active selection."""
        if not self._entries:
            return
        removed_sources = tuple(entry.source for entry in self._entries)
        self.selectionChanging.emit(self.current, None)
        self._entries.clear()
        self._current_index = -1
        self.changed.emit()
        self.selectionChanged.emit(None)
        self.resourcesInvalidated.emit(removed_sources)
