#    CuteCanvas - High-performance layered image editor
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
"""Polished public-API editor actions for the demonstration host."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from PySide6.QtCore import QObject, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCursor,
    QKeySequence,
    QPalette,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
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

from cutecanvas import (
    CuteCanvas,
    EditorCursorIntent,
    EditorIntent,
    LayerEdgeModificationResult,
    LayerPolicy,
    PixelSelectionModificationResult,
    RasterExtentPolicy,
)

from .history_controls import DemoHistoryControls
from .layer_policy import DemoLayerPolicyController
from .selection_modification_control import SelectionModificationDemoControl


class _DemoEditorCursorTheme:
    """Demonstrate host cursor artwork without owning editor interaction state."""

    def resolve_cursor(
        self,
        intent: EditorCursorIntent,
        *,
        device_pixel_ratio: float,
    ) -> QCursor | None:
        """Theme selection translation and defer every other semantic intent."""

        del device_pixel_ratio
        if intent is EditorCursorIntent.SELECTION_TRANSLATE:
            return QCursor(Qt.CursorShape.OpenHandCursor)
        return None


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
        qpane: CuteCanvas,
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
        self._qpane.setEditorCursorTheme(_DemoEditorCursorTheme())
        self.layer_policy = DemoLayerPolicyController(qpane, self)
        self._selection_actions = self._build_selection_actions()
        self._mask_shape_actions = self._build_mask_shape_actions()
        self.paint_bucket_action = self._tool_action(
            "Paint Bucket",
            CuteCanvas.CONTROL_MODE_PAINT_BUCKET,
            "G",
        )
        self.history = DemoHistoryControls(qpane, show_status, self)
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
        self.selection_modification = SelectionModificationDemoControl(
            qpane,
            show_status,
            self,
        )
        self.expand_selection_action = self.selection_modification.expand_action
        self.contract_selection_action = self.selection_modification.contract_action
        self.feather_selection_action = self.selection_modification.feather_action
        self.fill_selection_action = self._action(
            "Fill Selection",
            self._fill_selection,
            QKeySequence("Shift+Backspace"),
        )
        self.rasterize_mask_action = self._action(
            "Rasterize Mask Shapes",
            self._rasterize_mask,
        )
        self.expand_mask_action = self._action(
            "Expand Complete Mask...", self._expand_mask
        )
        self.contract_mask_action = self._action(
            "Contract Complete Mask...", self._contract_mask
        )
        self.feather_mask_action = self._action(
            "Feather Complete Mask...", self._feather_mask
        )
        for action in (
            self.expand_mask_action,
            self.contract_mask_action,
            self.feather_mask_action,
        ):
            action.setStatusTip(
                "Modify mask coverage inside the composition canvas aperture."
            )
        self.mask_opacity_action = self._action(
            "Set Mask Visual Opacity...", self._set_mask_opacity
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
        qpane.pixelSelectionModificationCompleted.connect(
            self._selection_modification_completed
        )
        qpane.layerEdgeModificationCompleted.connect(
            self._layer_edge_modification_completed
        )
        qpane.layerPixelsChanged.connect(self._layer_pixels_changed)
        qpane.floatingPixelEditChanged.connect(self.refresh)
        qpane.selectedLayerChanged.connect(self.refresh)
        qpane.editorPolicyChanged.connect(self.refresh)
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
        menu.addSection("Selection")
        for action in self._selection_actions:
            menu.addAction(action)
        menu.addSection("Mask")
        for action in self._mask_shape_actions:
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
        for action in (*self._selection_actions, *self._mask_shape_actions):
            action.triggered.connect(
                lambda _checked=False, selected=action: button.setDefaultAction(
                    selected
                )
            )
        toolbar.addWidget(container)
        return button

    def populate_edit_menu(self, menu: QMenu) -> None:
        """Populate an intentional editor menu without exposing lab controls."""
        self.history.populate(menu)
        menu.addSeparator()
        selection_menu = menu.addMenu("Selection Tool")
        for action in self._selection_actions:
            selection_menu.addAction(action)
        menu.addAction(self.select_all_action)
        menu.addAction(self.deselect_action)
        menu.addAction(self.invert_action)
        modification_menu = menu.addMenu("Modify Selection")
        modification_menu.addAction(self.expand_selection_action)
        modification_menu.addAction(self.contract_selection_action)
        modification_menu.addAction(self.feather_selection_action)
        menu.addAction(self.fill_selection_action)
        menu.addSeparator()
        menu.addAction(self.delete_pixels_action)
        menu.addSeparator()
        floating_menu = menu.addMenu("Floating Pixels")
        floating_menu.addAction(self.anchor_floating_action)
        floating_menu.addMenu(self._floating_target_menu)
        floating_menu.addAction(self.promote_floating_action)
        floating_menu.addSeparator()
        floating_menu.addAction(self.cancel_floating_action)

    def populate_layer_menu(self, menu: QMenu) -> None:
        """Add ordinary editable-layer creation to the demo's Layer menu."""
        menu.addAction(self.add_paint_layer_action)
        menu.addAction(self.rasterize_mask_action)
        menu.addAction(self.expand_mask_action)
        menu.addAction(self.contract_mask_action)
        menu.addAction(self.feather_mask_action)
        menu.addAction(self.mask_opacity_action)

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
        for action in (*self._selection_actions, *self._mask_shape_actions):
            action.setChecked(action.data() == mode)
        self.paint_bucket_action.setChecked(
            mode == CuteCanvas.CONTROL_MODE_PAINT_BUCKET
        )

    def refresh(self, *_args: object) -> None:
        """Refresh action availability from detached public snapshots."""
        scene = self._qpane.currentScene()
        selection = self._qpane.pixelSelectionState()
        has_selection = selection is not None and selection.has_selection
        panel_selection = (
            None
            if selection is None or selection.bounds is None
            else self._qpane.sceneToPanelRect(QRectF(selection.bounds))
        )
        selection_state = self._qpane.editorOperationState(EditorIntent.SELECT_PIXELS)
        delete_state = self._qpane.editorOperationState(EditorIntent.DELETE_PIXELS)
        floating = self._qpane.floatingPixelEditState()
        self.select_all_action.setEnabled(selection_state.allowed)
        self.deselect_action.setEnabled(has_selection)
        self.deselect_action.setStatusTip(
            "Clear the current pixel selection"
            if panel_selection is None
            else (
                "Clear the pixel selection shown at "
                f"({round(panel_selection.x())}, {round(panel_selection.y())})"
            )
        )
        self.invert_action.setEnabled(selection_state.allowed)
        self.selection_modification.set_enabled(has_selection)
        self.fill_selection_action.setEnabled(has_selection)
        self.rasterize_mask_action.setEnabled(self._qpane.activeMaskID() is not None)
        self.delete_pixels_action.setEnabled(
            has_selection and (delete_state.allowed or bool(delete_state.alternatives))
        )
        self.add_paint_layer_action.setEnabled(scene is not None)
        has_floating = floating is not None
        self.anchor_floating_action.setEnabled(has_floating)
        self.promote_floating_action.setEnabled(has_floating)
        self.cancel_floating_action.setEnabled(has_floating)
        self._floating_target_menu.setEnabled(has_floating)
        if self._floating_toolbar is not None:
            self._floating_toolbar.setVisible(has_floating)
        for action in self._selection_actions:
            action.setEnabled(selection_state.allowed)
        for action in self._mask_shape_actions:
            action.setEnabled(self._qpane.activeMaskID() is not None)

    def _build_selection_actions(self) -> tuple[QAction, ...]:
        """Create mutually exclusive shape tools with discoverable shortcuts."""
        group = QActionGroup(self)
        group.setExclusive(True)
        actions = (
            self._tool_action(
                "Rectangle Select",
                CuteCanvas.CONTROL_MODE_SELECT_RECTANGLE,
                "R",
            ),
            self._tool_action(
                "Ellipse Select",
                CuteCanvas.CONTROL_MODE_SELECT_ELLIPSE,
                "E",
            ),
            self._tool_action(
                "Lasso Select",
                CuteCanvas.CONTROL_MODE_SELECT_LASSO,
                "L",
            ),
            self._tool_action(
                "Polygon Select",
                CuteCanvas.CONTROL_MODE_SELECT_POLYGON,
                "P",
            ),
        )
        for action in actions:
            group.addAction(action)
        return actions

    def _build_mask_shape_actions(self) -> tuple[QAction, ...]:
        """Create retained mask-shape tools sharing the selection implementation."""
        group = QActionGroup(self)
        group.setExclusive(True)
        actions = (
            self._tool_action(
                "Rectangle Mask",
                CuteCanvas.CONTROL_MODE_MASK_RECTANGLE,
                "",
            ),
            self._tool_action(
                "Ellipse Mask",
                CuteCanvas.CONTROL_MODE_MASK_ELLIPSE,
                "",
            ),
            self._tool_action(
                "Lasso Mask",
                CuteCanvas.CONTROL_MODE_MASK_LASSO,
                "",
            ),
            self._tool_action(
                "Polygon Mask",
                CuteCanvas.CONTROL_MODE_MASK_POLYGON,
                "",
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

    def _selection_modification_completed(
        self,
        result: PixelSelectionModificationResult,
    ) -> None:
        """Present one terminal selection request without inferring completion."""
        if result.succeeded:
            self._show_status(f"Selection {result.operation.value} complete.")
        elif result.message:
            self._show_status(result.message)

    def _fill_selection(self) -> None:
        """Fill the active selection into the current editable target."""
        if self._qpane.fillSelection():
            self._show_status("Filled the active selection.")
        else:
            self._show_status("Select pixels and an editable layer first.")

    def _rasterize_mask(self) -> None:
        """Explicitly flatten retained geometry in the active mask."""
        mask_id = self._qpane.activeMaskID()
        if mask_id is not None and self._qpane.rasterizeMaskCoverage(mask_id):
            self._show_status("Rasterized retained mask shapes.")
        else:
            self._show_status("The active mask has no retained shapes to rasterize.")

    def _expand_mask(self) -> None:
        """Expand complete active-mask coverage through generic layer routing."""
        self._request_mask_edge("Expand Complete Mask", self._qpane.expandMaskEdges)

    def _contract_mask(self) -> None:
        """Contract complete active-mask coverage through generic layer routing."""
        self._request_mask_edge(
            "Contract Complete Mask",
            self._qpane.contractMaskEdges,
        )

    def _feather_mask(self) -> None:
        """Feather complete active-mask coverage through generic layer routing."""
        self._request_mask_edge("Feather Complete Mask", self._qpane.featherMaskEdges)

    def _request_mask_edge(
        self,
        title: str,
        request: Callable[[uuid.UUID, int], uuid.UUID | None],
    ) -> None:
        """Prompt for one whole-mask edge radius and submit it asynchronously."""
        mask_id = self._qpane.activeMaskID()
        pixels, accepted = QInputDialog.getInt(
            self._qpane,
            title,
            "Pixels:",
            4,
            1,
            1000,
        )
        if mask_id is not None and accepted and request(mask_id, pixels) is not None:
            self._show_status(f"{title} requested...")

    def _set_mask_opacity(self) -> None:
        """Change final mask presentation without editing scalar coverage."""
        mask_id = self._qpane.activeMaskID()
        percent, accepted = QInputDialog.getInt(
            self._qpane,
            "Mask Visual Opacity",
            "Percent:",
            50,
            0,
            100,
        )
        if (
            mask_id is not None
            and accepted
            and self._qpane.setMaskProperties(mask_id, opacity=percent / 100.0)
        ):
            self._show_status("Mask visual opacity updated.")

    def _layer_edge_modification_completed(
        self,
        result: LayerEdgeModificationResult,
    ) -> None:
        """Present terminal whole-layer work without guessing from request timing."""
        if result.succeeded:
            self._show_status(f"Layer {result.operation.value} complete.")
        elif result.message:
            self._show_status(result.message)

    def _delete_pixels(self) -> None:
        """Clear selected pixels from the selected editable layer."""
        if self._qpane.deleteSelectedPixels():
            return
        state = self._qpane.editorOperationState(EditorIntent.DELETE_PIXELS)
        if "rasterize" in state.alternatives:
            self._show_status(
                "The selected layer is not ready for pixel editing. Rasterize it "
                "and wait for completion."
            )
        elif state.denial == "host-policy-denied":
            self._show_status("The host editor policy disables pixel editing.")
        else:
            self._show_status("No editable selected pixels are available.")

    def _layer_pixels_changed(
        self,
        _scene_id: uuid.UUID,
        _layer_id: uuid.UUID,
        _resource_id: uuid.UUID,
    ) -> None:
        """Present durable pixel edits from buttons, keys, undo, or redo."""
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
        interaction: LayerPolicy,
    ) -> None:
        """Resolve floating pixels into a chosen compatible layer."""
        destination_policy = LayerPolicy(
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
            self.layer_policy.reconcile()
            self._show_status(f"Anchored floating pixels to {label or 'layer'}.")
            return
        self._qpane.setLayerInteractionPolicy(scene_id, layer_id, interaction)

    def _add_paint_layer(self) -> None:
        """Create and target an empty expanding RGBA paint layer."""
        self._paint_layer_count += 1
        layer_id = self._qpane.createPaintLayer(
            label=f"Paint {self._paint_layer_count}",
            extent_policy=RasterExtentPolicy.UNBOUNDED,
        )
        if layer_id is not None:
            self._set_mode(CuteCanvas.CONTROL_MODE_DRAW_BRUSH)
            self._show_status("Added an empty paint layer and armed the brush.")
