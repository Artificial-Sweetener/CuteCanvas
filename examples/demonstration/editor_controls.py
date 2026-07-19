#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Polished public-API editor actions for the demonstration host."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from PySide6.QtCore import QObject, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QImage,
    QKeySequence,
    QPainter,
    QPalette,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QStyle,
    QStyleOptionToolButton,
    QStylePainter,
    QToolBar,
    QToolButton,
    QWidget,
)

from qpane import QPane, QPaneLayerInteractionPolicy, RasterExtentPolicy


class _CenteredMenuToolButton(QToolButton):
    """Paint split-button text around the complete demo-toolbar control."""

    def sizeHint(self) -> QSize:
        """Reserve arrow-width clearance around the centered label."""
        hint = super().sizeHint()
        return QSize(hint.width() + self._menu_indicator_width(), hint.height())

    def paintEvent(self, _event: object) -> None:
        """Draw the native split frame and center its label across both halves."""
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        label = option.text
        option.text = ""
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ToolButton, option)
        self.style().drawItemText(
            painter,
            self._label_rect(),
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextShowMnemonic,
            option.palette,
            self.isEnabled(),
            label,
            QPalette.ColorRole.ButtonText,
        )

    def _label_rect(self) -> QRect:
        """Return the complete control rectangle used to center the label."""
        return self.rect()

    def _menu_indicator_width(self) -> int:
        """Return native menu-indicator width for the active platform style."""
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        return self.style().pixelMetric(
            QStyle.PixelMetric.PM_MenuButtonIndicator,
            option,
            self,
        )


class EditorControls(QObject):
    """Own coherent selection, history, and editable-layer demo actions."""

    def __init__(
        self,
        qpane: QPane,
        *,
        set_mode: Callable[[str], None],
        show_status: Callable[[str], None],
        parent: QObject,
    ) -> None:
        """Build actions and subscribe to public editor state."""
        super().__init__(parent)
        self._qpane = qpane
        self._set_mode = set_mode
        self._show_status = show_status
        self._paint_layer_count = 0
        self._policy_mask_id = None
        self._selection_actions = self._build_selection_actions()
        self.undo_action = self._action(
            "Undo",
            self._undo,
            QKeySequence.StandardKey.Undo,
        )
        self.redo_action = self._action(
            "Redo",
            self._redo,
            QKeySequence.StandardKey.Redo,
        )
        self.select_all_action = self._action(
            "Select All",
            self._select_all,
            QKeySequence.StandardKey.SelectAll,
        )
        self.deselect_action = self._action(
            "Deselect",
            self._deselect,
            QKeySequence("Ctrl+D"),
        )
        self.invert_action = self._action(
            "Invert Selection",
            self._invert,
            QKeySequence("Ctrl+Shift+I"),
        )
        self.delete_pixels_action = self._action(
            "Clear Selected Pixels",
            self._delete_pixels,
            QKeySequence(Qt.Key_Delete),
        )
        self.add_paint_layer_action = self._action(
            "Add Editable Paint Layer",
            self._add_paint_layer,
        )
        self.anchor_floating_action = self._action(
            "Anchor to Source Layer",
            self._anchor_floating,
        )
        self.promote_floating_action = self._action(
            "Move to New Layer",
            self._promote_floating,
            QKeySequence("Ctrl+Shift+J"),
        )
        self.cancel_floating_action = self._action(
            "Cancel Floating Pixels",
            self._cancel_floating,
        )
        self._floating_target_menu = QMenu("Anchor to Another Layer")
        self._floating_target_menu.aboutToShow.connect(self._populate_floating_targets)
        self._floating_toolbar: QToolBar | None = None
        qpane.pixelSelectionChanged.connect(self.refresh)
        qpane.floatingPixelEditChanged.connect(self.refresh)
        qpane.selectedLayerChanged.connect(self.refresh)
        qpane.sceneChanged.connect(self.refresh)
        qpane.sceneEditHistoryChanged.connect(self.refresh)
        self.refresh()

    @property
    def selection_actions(self) -> tuple[QAction, ...]:
        """Return selection tools in their intended menu order."""
        return self._selection_actions

    def add_selection_button(self, toolbar: QToolBar) -> QToolButton:
        """Add one compact last-used selection tool to ``toolbar``."""
        menu = QMenu(toolbar)
        for action in self._selection_actions:
            menu.addAction(action)
        container = QWidget(toolbar)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        button = _CenteredMenuToolButton(container)
        button.setPopupMode(QToolButton.MenuButtonPopup)
        button.setMenu(menu)
        button.setDefaultAction(self._selection_actions[0])
        button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        layout.addWidget(button)
        for action in self._selection_actions:
            action.triggered.connect(
                lambda _checked=False, selected=action: button.setDefaultAction(
                    selected
                )
            )
        toolbar.addWidget(container)
        return button

    def populate_edit_menu(self, menu: QMenu) -> None:
        """Populate an intentional editor menu without exposing lab controls."""
        menu.addAction(self.undo_action)
        menu.addAction(self.redo_action)
        menu.addSeparator()
        selection_menu = menu.addMenu("Selection Tool")
        for action in self._selection_actions:
            selection_menu.addAction(action)
        menu.addAction(self.select_all_action)
        menu.addAction(self.deselect_action)
        menu.addAction(self.invert_action)
        menu.addSeparator()
        menu.addAction(self.delete_pixels_action)
        menu.addAction(self.add_paint_layer_action)
        menu.addSeparator()
        floating_menu = menu.addMenu("Floating Pixels")
        floating_menu.addAction(self.anchor_floating_action)
        floating_menu.addMenu(self._floating_target_menu)
        floating_menu.addAction(self.promote_floating_action)
        floating_menu.addSeparator()
        floating_menu.addAction(self.cancel_floating_action)

    def add_floating_toolbar(self, window: QMainWindow) -> QToolBar:
        """Add a compact contextual bar shown only for unresolved pixels."""
        toolbar = QToolBar("Floating Pixels", window)
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        label = QLabel(" Floating pixels ", toolbar)
        toolbar.addWidget(label)
        toolbar.addAction(self.anchor_floating_action)
        target_button = QToolButton(toolbar)
        target_button.setText("Other Layer")
        target_button.setMenu(self._floating_target_menu)
        target_button.setPopupMode(QToolButton.InstantPopup)
        target_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        toolbar.addWidget(target_button)
        toolbar.addAction(self.promote_floating_action)
        toolbar.addAction(self.cancel_floating_action)
        window.addToolBar(Qt.TopToolBarArea, toolbar)
        self._floating_toolbar = toolbar
        self.refresh()
        return toolbar

    def sync_mode(self, mode: str) -> None:
        """Keep check state aligned with the active public tool mode."""
        for action in self._selection_actions:
            action.setChecked(action.data() == mode)

    def apply_layer_policy(self) -> None:
        """Permit edits only on the selected authoring layer; freeze images."""
        scene = self._qpane.currentScene()
        if scene is None:
            return
        frozen = QPaneLayerInteractionPolicy()
        selectable = QPaneLayerInteractionPolicy(selectable=True)
        editable = QPaneLayerInteractionPolicy(
            selectable=True,
            movable=True,
            pixel_editable=True,
        )
        selected = self._qpane.selectedLayer()
        selected_layer_id = None if selected is None else selected.layer_id
        active_mask_id = self._qpane.activeMaskID()
        active_mask_layer_id = next(
            (
                mask.layer_id
                for mask in self._qpane.listMasksForImage()
                if mask.mask_id == active_mask_id
            ),
            None,
        )
        if active_mask_id != self._policy_mask_id:
            self._policy_mask_id = active_mask_id
            selected_layer_id = active_mask_layer_id
        if selected_layer_id is None:
            selected_layer_id = active_mask_layer_id
        for layer in scene.layers:
            authoring_layer = layer.source_kind in {"mask", "raster"}
            policy = (
                editable
                if authoring_layer and layer.layer_id == selected_layer_id
                else selectable if authoring_layer else frozen
            )
            self._qpane.setLayerInteractionPolicy(
                scene.scene_id,
                layer.layer_id,
                policy,
            )
        if selected_layer_id is not None:
            self._qpane.setSelectedLayer(scene.scene_id, selected_layer_id)

    def select_active_mask_layer(self) -> None:
        """Align selected editor-layer identity with the active mask."""
        active_mask_id = self._qpane.activeMaskID()
        for mask in self._qpane.listMasksForImage():
            if (
                mask.mask_id == active_mask_id
                and mask.scene_id is not None
                and mask.layer_id is not None
            ):
                self._qpane.setLayerInteractionPolicy(
                    mask.scene_id,
                    mask.layer_id,
                    QPaneLayerInteractionPolicy(selectable=True),
                )
                self._qpane.setSelectedLayer(mask.scene_id, mask.layer_id)
                return

    def refresh(self, *_args: object) -> None:
        """Refresh action availability from detached public snapshots."""
        scene = self._qpane.currentScene()
        selection = self._qpane.pixelSelectionState()
        selected = self._qpane.selectedLayer()
        selected_layer = None
        if scene is not None and selected is not None:
            selected_layer = next(
                (
                    layer
                    for layer in scene.layers
                    if layer.layer_id == selected.layer_id
                ),
                None,
            )
        has_selection = selection is not None and selection.has_selection
        floating = self._qpane.floatingPixelEditState()
        editable = bool(
            selected_layer is not None
            and selected_layer.interaction.pixel_editable
            and selected_layer.source_kind in {"mask", "raster"}
        )
        self.undo_action.setEnabled(self._qpane.sceneEditUndoAvailable())
        self.redo_action.setEnabled(self._qpane.sceneEditRedoAvailable())
        self.select_all_action.setEnabled(scene is not None)
        self.deselect_action.setEnabled(has_selection)
        self.invert_action.setEnabled(scene is not None)
        self.delete_pixels_action.setEnabled(has_selection and editable)
        self.add_paint_layer_action.setEnabled(
            self._qpane.currentImage is not None and scene is not None
        )
        has_floating = floating is not None
        self.anchor_floating_action.setEnabled(has_floating)
        self.promote_floating_action.setEnabled(has_floating)
        self.cancel_floating_action.setEnabled(has_floating)
        self._floating_target_menu.setEnabled(has_floating)
        if self._floating_toolbar is not None:
            self._floating_toolbar.setVisible(has_floating)
        for action in self._selection_actions:
            action.setEnabled(scene is not None)

    def _build_selection_actions(self) -> tuple[QAction, ...]:
        """Create mutually exclusive shape tools with discoverable shortcuts."""
        group = QActionGroup(self)
        group.setExclusive(True)
        actions = (
            self._tool_action(
                "Rectangle Select",
                QPane.CONTROL_MODE_SELECT_RECTANGLE,
                "R",
            ),
            self._tool_action(
                "Ellipse Select",
                QPane.CONTROL_MODE_SELECT_ELLIPSE,
                "E",
            ),
            self._tool_action(
                "Lasso Select",
                QPane.CONTROL_MODE_SELECT_LASSO,
                "L",
            ),
        )
        for action in actions:
            group.addAction(action)
        return actions

    def _tool_action(self, label: str, mode: str, shortcut: str) -> QAction:
        """Build one checkable public control-mode action."""
        action = QAction(label, self, checkable=True)
        action.setData(mode)
        action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(lambda _checked=False: self._set_mode(mode))
        return action

    def _action(
        self,
        label: str,
        callback: Callable[[], None],
        shortcut: QKeySequence | QKeySequence.StandardKey | None = None,
    ) -> QAction:
        """Build one window-scoped editor action."""
        action = QAction(label, self)
        if shortcut is not None:
            action.setShortcut(shortcut)
        action.triggered.connect(callback)
        return action

    def _undo(self) -> None:
        """Undo one chronological composition edit."""
        if self._qpane.undoSceneEdit():
            self._show_status("Undid the last editor change.")

    def _redo(self) -> None:
        """Redo one chronological composition edit."""
        if self._qpane.redoSceneEdit():
            self._show_status("Redid the editor change.")

    def _select_all(self) -> None:
        """Select the complete composition canvas."""
        if self._qpane.selectAllPixels():
            self._show_status("Selected the full canvas.")

    def _deselect(self) -> None:
        """Clear composition pixel selection."""
        if self._qpane.clearPixelSelection():
            self._show_status("Selection cleared.")

    def _invert(self) -> None:
        """Invert selection within composition bounds."""
        if self._qpane.invertPixelSelection():
            self._show_status("Selection inverted.")

    def _delete_pixels(self) -> None:
        """Clear selected pixels from the selected editable layer."""
        if self._qpane.deleteSelectedPixels():
            self._show_status("Cleared selected pixels from the active layer.")

    def _anchor_floating(self) -> None:
        """Resolve the transient payload into its source layer."""
        if self._qpane.anchorFloatingPixels():
            self._show_status("Anchored floating pixels to their source layer.")

    def _promote_floating(self) -> None:
        """Resolve the transient payload as a new composition layer."""
        if self._qpane.promoteFloatingPixels() is not None:
            self._show_status("Moved floating pixels to a new layer.")

    def _cancel_floating(self) -> None:
        """Discard transient displacement and preserve the source layer."""
        if self._qpane.cancelFloatingPixels():
            self._show_status("Cancelled floating pixels.")

    def _populate_floating_targets(self) -> None:
        """Build compatible destination actions from the current public scene."""
        self._floating_target_menu.clear()
        state = self._qpane.floatingPixelEditState()
        scene = self._qpane.currentScene()
        if state is None or scene is None:
            unavailable = self._floating_target_menu.addAction("No floating pixels")
            unavailable.setEnabled(False)
            return
        source = next(
            (
                layer
                for layer in scene.layers
                if layer.layer_id == state.source_layer_id
            ),
            None,
        )
        candidates = (
            ()
            if source is None
            else tuple(
                layer
                for layer in scene.layers
                if layer.layer_id != source.layer_id
                and layer.source_kind == source.source_kind
                and layer.source_kind in {"mask", "raster"}
            )
        )
        for layer in candidates:
            action = self._floating_target_menu.addAction(
                layer.label or layer.source_kind.title()
            )
            action.triggered.connect(
                lambda _checked=False, target=layer: self._anchor_to_layer(
                    scene.scene_id,
                    target.layer_id,
                    target.label,
                    target.interaction,
                )
            )
        if not candidates:
            unavailable = self._floating_target_menu.addAction(
                "No compatible editable layers"
            )
            unavailable.setEnabled(False)

    def _anchor_to_layer(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        label: str | None,
        interaction: QPaneLayerInteractionPolicy,
    ) -> None:
        """Resolve floating pixels into a chosen compatible layer."""
        destination_policy = QPaneLayerInteractionPolicy(
            selectable=interaction.selectable,
            movable=interaction.movable,
            pixel_editable=True,
        )
        if not self._qpane.setLayerInteractionPolicy(
            scene_id,
            layer_id,
            destination_policy,
        ):
            return
        if self._qpane.anchorFloatingPixels(scene_id, layer_id):
            self.apply_layer_policy()
            self._show_status(f"Anchored floating pixels to {label or 'layer'}.")
            return
        self._qpane.setLayerInteractionPolicy(scene_id, layer_id, interaction)

    def _add_paint_layer(self) -> None:
        """Create visible editable RGBA content through public layer APIs."""
        source = self._qpane.currentImage
        if source is None or source.isNull():
            return
        image = QImage(source.size(), QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(65, 190, 235, 150))
        width = max(24.0, image.width() * 0.22)
        height = max(24.0, image.height() * 0.22)
        painter.drawEllipse(
            QRectF(
                image.width() * 0.39,
                image.height() * 0.39,
                width,
                height,
            )
        )
        painter.end()
        self._paint_layer_count += 1
        layer_id = self._qpane.addEditableRasterLayer(
            image,
            label=f"Paint {self._paint_layer_count}",
            interaction=QPaneLayerInteractionPolicy(
                selectable=True,
                movable=True,
                pixel_editable=True,
            ),
            extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
        )
        scene = self._qpane.currentScene()
        if layer_id is not None and scene is not None:
            self._qpane.setSelectedLayer(scene.scene_id, layer_id)
            self._show_status("Added and selected an editable paint layer.")
