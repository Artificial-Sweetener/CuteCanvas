#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Authoritative composition-and-layer tree for the demonstration host."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from PySide6.QtCore import QItemSelectionModel, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QMenu,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from qpane import CompositionEntry, CompositionLayerEntry, CompositionSnapshot, QPane

FocusPolicy = Callable[[str], None]
_BROWSER_ROLE = Qt.ItemDataRole.UserRole


class CompositionBrowser(QTreeWidget):
    """Project every composition layer and synchronize authoritative selection."""

    layerPropertiesRequested = Signal(object, object)
    compositionPropertiesRequested = Signal(object)

    def __init__(
        self,
        qpane: QPane,
        *,
        on_focus_requested: FocusPolicy,
        parent: QWidget | None = None,
    ) -> None:
        """Bind public composition snapshots to a compact nested tree."""
        super().__init__(parent)
        self._qpane = qpane
        self._on_focus_requested = on_focus_requested
        self._composition_items: dict[uuid.UUID, QTreeWidgetItem] = {}
        self._entries: dict[uuid.UUID, CompositionEntry] = {}
        self._layer_items: dict[tuple[uuid.UUID, uuid.UUID], QTreeWidgetItem] = {}
        self._syncing = False
        self._pending_snapshot: CompositionSnapshot | None = None
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._apply_pending_refresh)
        self.setHeaderHidden(True)
        self.setUniformRowHeights(True)
        self.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setExpandsOnDoubleClick(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.itemClicked.connect(self._activate_item)
        self.customContextMenuRequested.connect(self._open_context_menu)
        qpane.compositionChanged.connect(self.refresh)
        qpane.compositionSelectionChanged.connect(self._sync_selection)
        qpane.selectedLayerChanged.connect(self._sync_selection)
        self._rebuild(qpane.getCompositionSnapshot())

    def dropEvent(self, event: QDropEvent) -> None:
        """Commit same-composition tree drags through public stack history."""
        moved = self.currentItem()
        source_parent = None if moved is None else moved.parent()
        source_payload = None if moved is None else moved.data(0, _BROWSER_ROLE)
        target = self.itemAt(event.position().toPoint())
        target_parent = (
            target
            if target is not None and target.parent() is None
            else (None if target is None else target.parent())
        )
        if (
            source_parent is None
            or target_parent is not source_parent
            or not source_payload
            or source_payload[0] != "layer"
        ):
            event.ignore()
            return
        super().dropEvent(event)
        self._commit_visual_reorder(moved, source_payload)

    def _commit_visual_reorder(
        self,
        moved: QTreeWidgetItem,
        payload: tuple[object, ...],
    ) -> None:
        """Translate one completed topmost-first tree move into render order."""
        parent = moved.parent()
        if parent is None:
            self.refresh()
            return
        topmost_index = parent.indexOfChild(moved)
        render_index = parent.childCount() - 1 - topmost_index
        composition_id = payload[1]
        layer_id = payload[2]
        if not isinstance(composition_id, uuid.UUID) or not isinstance(
            layer_id, uuid.UUID
        ):
            self.refresh()
            return
        self._qpane.openComposition(composition_id)
        scene = self._qpane.currentScene()
        if scene is None or not self._qpane.setLayerIndex(
            scene.scene_id,
            layer_id,
            render_index,
        ):
            self.refresh()
            return
        self._qpane.setSelectedLayer(scene.scene_id, layer_id)
        self._on_focus_requested("image")
        self.refresh()

    def refresh(self, snapshot: CompositionSnapshot | None = None) -> None:
        """Queue the latest detached snapshot outside the active Qt input event."""
        self._pending_snapshot = snapshot or self._qpane.getCompositionSnapshot()
        if not self._refresh_timer.isActive():
            self._refresh_timer.start(0)

    def _apply_pending_refresh(self) -> None:
        """Apply one coalesced snapshot after the originating input event returns."""
        snapshot = self._pending_snapshot
        self._pending_snapshot = None
        if snapshot is not None:
            self._rebuild(snapshot)

    def _rebuild(self, state: CompositionSnapshot) -> None:
        """Rebuild rows from one detached public composition snapshot."""
        expanded = {
            composition_id
            for composition_id, item in self._composition_items.items()
            if item.isExpanded()
        }
        self._syncing = True
        try:
            self.clear()
            self._composition_items.clear()
            self._entries = dict(state.compositions)
            self._layer_items.clear()
            for index, composition_id in enumerate(state.order):
                entry = state.compositions.get(composition_id)
                if entry is None:
                    continue
                composition_item = self._composition_item(index, entry)
                self.addTopLevelItem(composition_item)
                self._composition_items[composition_id] = composition_item
                for layer in reversed(entry.layers):
                    layer_item = self._layer_item(composition_id, layer)
                    composition_item.addChild(layer_item)
                    self._layer_items[(composition_id, layer.layer_id)] = layer_item
                composition_item.setExpanded(
                    composition_id in expanded
                    or composition_id == state.current_composition_id
                )
        finally:
            self._syncing = False
        self._sync_selection()

    def _activate_item(self, item: QTreeWidgetItem, _column: int) -> None:
        """Activate the composition or exact layer represented by ``item``."""
        if self._syncing:
            return
        payload = item.data(0, _BROWSER_ROLE)
        if not payload:
            return
        composition_id = payload[1]
        self._qpane.openComposition(composition_id)
        if payload[0] == "layer":
            layer_id = payload[2]
            source_kind = payload[3]
            source_id = payload[4]
            if source_kind == "mask":
                self._qpane.setActiveMaskID(source_id)
            scene = self._qpane.currentScene()
            if scene is not None:
                self._qpane.setSelectedLayer(scene.scene_id, layer_id)
        self._on_focus_requested("image")
        self._sync_selection()

    def _sync_selection(self, *_args: object) -> None:
        """Mirror active composition and selected-layer identity in the tree."""
        if self._syncing:
            return
        self._syncing = True
        try:
            composition_id = self._qpane.currentCompositionID()
            selected = self._qpane.selectedLayer()
            target = None
            if composition_id is not None and selected is not None:
                target = self._layer_items.get((composition_id, selected.layer_id))
            if target is None and composition_id is not None:
                target = self._composition_items.get(composition_id)
            self.clearSelection()
            if target is None:
                return
            target.setSelected(True)
            parent = target.parent()
            if parent is not None:
                parent.setExpanded(True)
            self.setCurrentItem(
                target,
                0,
                QItemSelectionModel.SelectionFlag.Select
                | QItemSelectionModel.SelectionFlag.Current,
            )
        finally:
            self._syncing = False

    def _open_context_menu(self, position: QPoint) -> None:
        """Offer focused document and layer actions without permanent controls."""
        item = self.itemAt(position)
        payload = None if item is None else item.data(0, _BROWSER_ROLE)
        if not payload:
            return
        menu = QMenu(self)
        if payload[0] == "composition":
            composition_id = payload[1]
            entry = self._entries.get(composition_id)
            properties = menu.addAction("Composition Properties…")
            remove = menu.addAction("Remove Composition")
            remove.setEnabled(entry is not None and entry.policy.removable)
            chosen = menu.exec(self.viewport().mapToGlobal(position))
            if chosen is properties:
                self._activate_item(item, 0)
                self.compositionPropertiesRequested.emit(composition_id)
            elif chosen is remove:
                self._qpane.removeComposition(composition_id)
            return
        if payload[0] != "layer":
            return
        properties = menu.addAction("Layer Properties…")
        remove = menu.addAction("Remove Layer")
        composition_id = payload[1]
        layer_id = payload[2]
        entry = self._entries.get(composition_id)
        layer = (
            None
            if entry is None
            else next(
                (
                    candidate
                    for candidate in entry.layers
                    if candidate.layer_id == layer_id
                ),
                None,
            )
        )
        remove.setEnabled(layer is not None and layer.interaction.removable)
        chosen = menu.exec(self.viewport().mapToGlobal(position))
        if chosen is None:
            return
        self._activate_item(item, 0)
        if chosen is properties:
            self.layerPropertiesRequested.emit(composition_id, layer_id)
        elif chosen is remove:
            scene = self._qpane.currentScene()
            if scene is not None:
                self._qpane.removeLayer(scene.scene_id, layer_id)

    @staticmethod
    def _composition_item(index: int, entry: CompositionEntry) -> QTreeWidgetItem:
        """Create one top-level composition row."""
        suffix = " + compare" if entry.comparison.enabled else ""
        item = QTreeWidgetItem([f"{index + 1}. {entry.title}{suffix}"])
        item.setData(0, _BROWSER_ROLE, ("composition", entry.composition_id))
        item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDropEnabled)
        item.setToolTip(0, f"{entry.scene_layer_count} layers")
        return item

    @staticmethod
    def _layer_item(
        composition_id: uuid.UUID,
        layer: CompositionLayerEntry,
    ) -> QTreeWidgetItem:
        """Create one indented layer row from detached browser metadata."""
        fallback = {
            "base-image": "Background",
            "mask": "Mask",
            "placed-asset": "Placed Image",
            "raster": "Paint Layer",
            "vector": "Vector Layer",
        }.get(layer.role, layer.source_kind.replace("-", " ").title())
        item = QTreeWidgetItem([layer.label or fallback])
        item.setData(
            0,
            _BROWSER_ROLE,
            (
                "layer",
                composition_id,
                layer.layer_id,
                layer.source_kind,
                layer.source_id,
            ),
        )
        flags = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
        if layer.interaction.reorderable:
            flags |= Qt.ItemFlag.ItemIsDragEnabled
        item.setFlags(flags)
        item.setToolTip(0, layer.source_kind.replace("-", " ").title())
        return item
