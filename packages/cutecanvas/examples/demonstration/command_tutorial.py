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
"""Teach a polished menu and toolbar shell over public CuteCanvas commands."""

from __future__ import annotations

from collections.abc import Callable

from cutecanvas import CuteCanvas
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMainWindow, QToolBar

from demonstration.canvas_geometry_dialog import CanvasGeometryDialog
from demonstration.composition_tutorial import (
    CompositionTutorialController,
)
from demonstration.configuration_tutorial import (
    ConfigurationTutorialController,
)
from demonstration.extension_tutorial import ExtensionTutorialController
from demonstration.tool_mode_tutorial import ToolModeTutorialController
from demonstration.workspace_tutorial import WorkspaceTutorialController


class CommandTutorialController:
    """Own actions, menus, toolbars, and their derived enabled state."""

    def __init__(
        self,
        canvas: CuteCanvas,
        parent: QMainWindow,
        *,
        workspace: WorkspaceTutorialController,
        tools: ToolModeTutorialController,
        compositions: CompositionTutorialController,
        configuration: ConfigurationTutorialController,
        extensions: ExtensionTutorialController,
        masks_available: Callable[[], bool],
        show_reference: Callable[[], None],
        show_presentations: Callable[[], None],
        show_status: Callable[[str], None],
        refresh_mask_status: Callable[[], None],
    ) -> None:
        """Build host commands from explicit concern-specific collaborators."""
        self._canvas = canvas
        self._parent = parent
        self._workspace = workspace
        self._tools = tools
        self._compositions = compositions
        self._configuration = configuration
        self._extensions = extensions
        self._masks_available = masks_available
        self._show_reference = show_reference
        self._show_presentations = show_presentations
        self._show_status = show_status
        self._refresh_mask_status = refresh_mask_status
        self._canvas_geometry_dialog: CanvasGeometryDialog | None = None
        self._create_actions()
        self._create_menus()
        self.toolbar: QToolBar | None = None
        self._floating_pixels_toolbar: QToolBar | None = None
        self.build_toolbar()

    def connect_signals(self) -> None:
        """Refresh command presentation from public editor notifications."""
        self._canvas.compositionChanged.connect(
            lambda _snapshot: self.handle_composition_event()
        )
        self._canvas.compositionChanged.connect(
            lambda _snapshot: self.refresh_composition_actions()
        )
        self._canvas.compositionSelectionChanged.connect(
            lambda _composition_id: self.refresh_tools()
        )

    def prime(self) -> None:
        """Populate command state after the starter composition is available."""
        self.handle_composition_event()
        self.refresh_tools()

    def build_toolbar(self) -> None:
        """Rebuild the compact tools toolbar after extension changes."""
        if self.toolbar is not None:
            self._parent.removeToolBar(self.toolbar)
        self.toolbar = QToolBar("Tools", self._parent)
        self.toolbar.setMovable(False)
        self.toolbar.setOrientation(Qt.Vertical)
        self.toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._parent.addToolBar(Qt.LeftToolBarArea, self.toolbar)
        if self._floating_pixels_toolbar is None:
            self._floating_pixels_toolbar = (
                self._tools.editor_controls.add_floating_toolbar(self._parent)
            )
        self._tools.build_context_toolbars()

        def add_group(actions: list[QAction | None]) -> bool:
            """Append a toolbar group and report whether it had content."""
            added = False
            for action in actions:
                if action is not None:
                    self.toolbar.addAction(action)
                    added = True
            return added

        navigation_added = add_group(
            [
                self.previous_composition_action,
                self.next_composition_action,
            ]
        )
        composition_added = add_group([self.place_composition_action])
        mode_actions = self._tools.mode_actions()
        if (navigation_added or composition_added) and any(
            action is not None for action in mode_actions
        ):
            self.toolbar.addSeparator()
        modes_added = add_group(mode_actions)
        self._tools.editor_controls.add_selection_button(self.toolbar)
        self._tools.vector_controls.add_tool_button(self.toolbar)
        self.toolbar.addAction(self._tools.cycle_mode_action)
        mask_actions = [
            self.add_mask_action,
            self.delete_mask_action,
            self.load_mask_action,
            self.save_mask_action,
            self.cycle_masks_backward_action,
            self.cycle_masks_forward_action,
        ]
        if modes_added and any(action is not None for action in mask_actions):
            self.toolbar.addSeparator()
        add_group(mask_actions)

    def refresh_tools(self) -> None:
        """Apply composition and feature policy to editor and mask actions."""
        self._tools.refresh_availability()
        mask_enabled = (
            self._masks_available() and self._canvas.currentCompositionID() is not None
        )
        for action in (
            self.add_mask_action,
            self.delete_mask_action,
            self.load_mask_action,
            self.save_mask_action,
            self.cycle_masks_backward_action,
            self.cycle_masks_forward_action,
        ):
            if action is not None:
                action.setEnabled(mask_enabled)
                if not mask_enabled:
                    self._set_checked(action, False)
        self._refresh_mask_status()

    def handle_composition_event(self) -> None:
        """Refresh command state from authoritative composition snapshots."""
        count = len(self._canvas.editor.compositions)
        self.update_action_states(count)
        self.set_delete_mask_enabled(bool(self._canvas.maskIDsForComposition()))
        self.refresh_tools()

    def update_action_states(self, count: int) -> None:
        """Enable composition actions from the number of open compositions."""
        has_compositions = count > 0
        for action, base_enabled in self._composition_actions:
            action.setEnabled(base_enabled and has_compositions)
        self.place_composition_action.setEnabled(count > 1)
        self._compositions.maybe_auto_show(count)
        self.refresh_composition_actions()

    def refresh_composition_actions(self) -> None:
        """Enable saving only while an editable composition is open."""
        self.save_composition_action.setEnabled(
            self._canvas.editor.compositions.current is not None
        )

    def set_delete_mask_enabled(self, enabled: bool) -> None:
        """Mirror derived mask presence into the optional delete command."""
        if self.delete_mask_action is not None:
            self.delete_mask_action.setEnabled(enabled)

    def _create_actions(self) -> None:
        """Create file, composition, mask, view, and extension commands."""
        self.open_images_action = QAction("Open Images...", self._parent)
        self.open_images_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_images_action.triggered.connect(self._workspace.open_images_dialog)
        self.open_composition_action = QAction("Open Composition…", self._parent)
        self.open_composition_action.setShortcut(QKeySequence("Ctrl+Alt+O"))
        self.open_composition_action.triggered.connect(
            self._workspace.open_composition_dialog
        )
        self.save_composition_action = QAction("Save Workspace…", self._parent)
        self.save_composition_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.save_composition_action.triggered.connect(
            self._workspace.save_composition_dialog
        )
        self.place_embedded_action = QAction("Place Embedded…", self._parent)
        self.place_embedded_action.triggered.connect(
            self._workspace.place_embedded_dialog
        )
        self.place_linked_action = QAction("Place Linked…", self._parent)
        self.place_linked_action.triggered.connect(self._workspace.place_linked_dialog)
        self.clear_action = QAction("Close All", self._parent)
        self.clear_action.triggered.connect(self._workspace.close_all_compositions)
        self.presentations_action = QAction("Multi-view Inspection…", self._parent)
        self.presentations_action.triggered.connect(self._show_presentations)
        self.canvas_geometry_action = QAction("Canvas Geometry…", self._parent)
        self.canvas_geometry_action.triggered.connect(self._show_canvas_geometry)
        self.previous_composition_action = QAction("◀ Prev", self._parent)
        self.previous_composition_action.setShortcut(Qt.Key_Left)
        self.previous_composition_action.triggered.connect(
            lambda: self._workspace.step_composition(-1)
        )
        self.next_composition_action = QAction("Next ▶", self._parent)
        self.next_composition_action.setShortcut(Qt.Key_Right)
        self.next_composition_action.triggered.connect(
            lambda: self._workspace.step_composition(1)
        )
        self.place_composition_action = QAction("Place Composition", self._parent)
        self.place_composition_action.triggered.connect(
            self._workspace.place_next_composition
        )
        self._create_mask_actions()
        self.config_action = QAction("Config", self._parent)
        self.config_action.triggered.connect(self._configuration.open_dialog)
        self.composition_panel_action = QAction(
            "Layers Panel", self._parent, checkable=True
        )
        self._compositions.bind_toggle_action(self.composition_panel_action)
        self.quick_reference_action = QAction("Quick Reference", self._parent)
        self.quick_reference_action.triggered.connect(self._show_reference)
        self.overlay_hook_action = QAction(
            "Custom Overlay (Hook)", self._parent, checkable=True
        )
        self.overlay_hook_action.toggled.connect(
            self._extensions.handle_custom_overlay_toggled
        )
        self.cursor_hook_action = QAction(
            "Custom Cursor Tool", self._parent, checkable=True
        )
        self.cursor_hook_action.toggled.connect(
            self._extensions.handle_custom_tool_toggled
        )
        self.lens_hook_action = QAction(
            "Custom Cursor + Overlay", self._parent, checkable=True
        )
        self.lens_hook_action.toggled.connect(self._extensions.handle_lens_toggled)
        self._composition_actions = [
            (self.clear_action, True),
            (self.previous_composition_action, True),
            (self.next_composition_action, True),
            (self.place_composition_action, True),
            (self.place_embedded_action, True),
            (self.place_linked_action, True),
            (self.canvas_geometry_action, True),
        ]
        self._composition_actions.extend(
            (action, True)
            for action in (
                self.add_mask_action,
                self.delete_mask_action,
                self.load_mask_action,
                self.save_mask_action,
                self.cycle_masks_backward_action,
                self.cycle_masks_forward_action,
            )
            if action is not None
        )

    def _create_mask_actions(self) -> None:
        """Create mask commands only for a mask-capable host configuration."""
        self.add_mask_action: QAction | None = None
        self.delete_mask_action: QAction | None = None
        self.load_mask_action: QAction | None = None
        self.save_mask_action: QAction | None = None
        self.cycle_masks_backward_action: QAction | None = None
        self.cycle_masks_forward_action: QAction | None = None
        if not self._masks_available():
            return
        self.add_mask_action = QAction("Add Mask", self._parent)
        self.add_mask_action.triggered.connect(self._workspace.add_mask)
        self.delete_mask_action = QAction("Delete Mask", self._parent)
        self.delete_mask_action.triggered.connect(self._workspace.delete_active_mask)
        self.load_mask_action = QAction("Load Mask...", self._parent)
        self.load_mask_action.setShortcut(QKeySequence("Ctrl+Shift+O"))
        self.load_mask_action.triggered.connect(self._workspace.load_mask_dialog)
        self.save_mask_action = QAction("Save Mask...", self._parent)
        self.save_mask_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_mask_action.triggered.connect(self._workspace.save_active_mask_dialog)
        self.cycle_masks_forward_action = QAction("Mask Up", self._parent)
        self.cycle_masks_forward_action.triggered.connect(
            self._workspace.cycle_masks_forward
        )
        self.cycle_masks_backward_action = QAction("Mask Down", self._parent)
        self.cycle_masks_backward_action.triggered.connect(
            self._workspace.cycle_masks_backward
        )

    def _create_menus(self) -> None:
        """Build a deliberate editor menu hierarchy from the command owners."""
        menu_bar = self._parent.menuBar()
        menu_bar.clear()
        file_menu = menu_bar.addMenu("&File")
        file_menu.addAction(self.open_composition_action)
        file_menu.addAction(self.save_composition_action)
        file_menu.addSeparator()
        file_menu.addAction(self.open_images_action)
        file_menu.addSeparator()
        file_menu.addAction(self.place_embedded_action)
        file_menu.addAction(self.place_linked_action)
        file_menu.addSeparator()
        file_menu.addAction(self.clear_action)
        file_menu.addSeparator()
        file_menu.addAction("Exit").triggered.connect(self._parent.close)
        edit_menu = menu_bar.addMenu("&Edit")
        self._tools.editor_controls.populate_edit_menu(edit_menu)
        edit_menu.addSeparator()
        self._tools.editor_policy_controls.populate_menu(
            edit_menu.addMenu("Editor Capabilities")
        )
        layer_menu = menu_bar.addMenu("&Layer")
        self._tools.editor_controls.populate_layer_menu(layer_menu)
        self._tools.vector_controls.populate_layer_menu(layer_menu)
        canvas_menu = menu_bar.addMenu("&Canvas")
        canvas_menu.addAction(self.canvas_geometry_action)
        view_menu = menu_bar.addMenu("&View")
        view_menu.addAction(self.presentations_action)
        view_menu.addSeparator()
        view_menu.addAction(self.composition_panel_action)
        view_menu.addAction(self.quick_reference_action)
        view_menu.addSeparator()
        view_menu.addAction(self.place_composition_action)
        view_menu.addSeparator()
        self._configuration.build_diagnostics_menu(
            view_menu.addMenu("Diagnostics Overlay")
        )
        hooks_menu = menu_bar.addMenu("Hooks")
        hooks_menu.addAction(self.overlay_hook_action)
        hooks_menu.addAction(self.cursor_hook_action)
        hooks_menu.addAction(self.lens_hook_action)
        menu_bar.addAction(self.config_action)

    def _show_canvas_geometry(self) -> None:
        """Open the reusable public canvas geometry workflow dialog."""
        if self._canvas_geometry_dialog is None:
            self._canvas_geometry_dialog = CanvasGeometryDialog(
                self._canvas,
                show_status=self._show_status,
                parent=self._parent,
            )
        self._canvas_geometry_dialog.refresh()
        self._canvas_geometry_dialog.show()
        self._canvas_geometry_dialog.raise_()
        self._canvas_geometry_dialog.activateWindow()

    @staticmethod
    def _set_checked(action: QAction, checked: bool) -> None:
        """Set action state without invoking its connected command."""
        action.blockSignals(True)
        action.setChecked(checked)
        action.blockSignals(False)
