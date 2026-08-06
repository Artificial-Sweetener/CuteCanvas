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
"""Catalog presentation widgets for the QPane viewer example."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qpane import ViewerCatalog


class CatalogPanel(QWidget):
    """Present a compact, original-style image catalog tree."""

    currentEntryReactivated = Signal(object)

    def __init__(self, catalog: ViewerCatalog, parent: QWidget | None = None) -> None:
        """Build the tree and synchronize it with ``catalog``."""
        super().__init__(parent)
        self.setObjectName("catalogPanel")
        self.setMinimumWidth(220)
        self.setMaximumWidth(380)
        self._catalog = catalog
        self._thumbnails: dict[object, QImage] = {}
        title = QLabel("Catalog")
        title.setObjectName("catalogTitle")
        title_font = QFont(title.font())
        title_font.setBold(True)
        title.setFont(title_font)
        self.tree = QTreeWidget()
        self.tree.setObjectName("catalogTree")
        self.tree.setHeaderHidden(True)
        self.tree.setIconSize(QSize(72, 48))
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(title)
        layout.addWidget(self.tree)
        self.tree.currentItemChanged.connect(self._activate_item)
        self.tree.itemActivated.connect(self._reactivate_item)
        catalog.changed.connect(self.refresh)
        self.refresh()

    def set_thumbnail(self, entry_id: object, thumbnail: QImage) -> None:
        """Store one worker-produced preview and refresh its catalog row."""
        if thumbnail.isNull():
            return
        self._thumbnails[entry_id] = QImage(thumbnail)
        self.refresh()

    def discard_thumbnail(self, entry_id: object) -> None:
        """Discard derived presentation data for a removed catalog entry."""
        self._thumbnails.pop(entry_id, None)

    def refresh(self) -> None:
        """Rebuild the small host tree from the catalog snapshot."""
        self.tree.blockSignals(True)
        self.tree.clear()
        root = QTreeWidgetItem([f"Images ({len(self._catalog.entries)})"])
        root.setExpanded(True)
        self.tree.addTopLevelItem(root)
        selected_item: QTreeWidgetItem | None = None
        for index, entry in enumerate(self._catalog.entries):
            item = QTreeWidgetItem([entry.label])
            item.setData(0, Qt.ItemDataRole.UserRole, index)
            item.setToolTip(
                0,
                f"{entry.label}\n{entry.size.width()} × {entry.size.height()} px",
            )
            thumbnail = self._thumbnails.get(entry.entry_id)
            if thumbnail is not None:
                item.setIcon(0, QIcon(QPixmap.fromImage(thumbnail)))
            root.addChild(item)
            if index == self._catalog.current_index:
                selected_item = item
        if selected_item is not None:
            self.tree.setCurrentItem(selected_item)
        self.tree.blockSignals(False)

    def _activate_item(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        """Route a clicked image row to the catalog owner."""
        if current is None:
            return
        index = current.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(index, int):
            self._catalog.select(index)

    def _reactivate_item(self, item: QTreeWidgetItem, _column: int) -> None:
        """Publish activation when the selected row already owns focus."""
        index = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(index, int) and index == self._catalog.current_index:
            self.currentEntryReactivated.emit(self._catalog.current)
