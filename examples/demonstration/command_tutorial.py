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

from examples.demonstration.catalog.builders import build_catalog_snapshot
from examples.demonstration.catalog_tutorial import CatalogTutorialController
from examples.demonstration.configuration_tutorial import (
    ConfigurationTutorialController,
)
from examples.demonstration.extension_tutorial import ExtensionTutorialController
from examples.demonstration.tool_mode_tutorial import ToolModeTutorialController
from examples.demonstration.workspace_tutorial import WorkspaceTutorialController


class CommandTutorialController:
    """Own actions, menus, toolbars, and their derived enabled state."""

    def __init__(
        self,
        canvas: CuteCanvas,
        parent: QMainWindow,
        *,
        workspace: WorkspaceTutorialController,
        tools: ToolModeTutorialController,
        catalog: CatalogTutorialController,
        configuration: ConfigurationTutorialController,
        extensions: ExtensionTutorialController,
        masks_available: Callable[[], bool],
        all_images_linked: Callable[[], bool],
        show_reference: Callable[[], None],
        show_status: Callable[[str], None],
        refresh_mask_status: Callable[[], None],
    ) -> None:
        """Build host commands from explicit concern-specific collaborators."""
        self._canvas = canvas
        self._parent = parent
        self._workspace = workspace
        self._tools = tools
        self._catalog = catalog
        self._configuration = configuration
        self._extensions = extensions
        self._masks_available = masks_available
        self._all_images_linked = all_images_linked
        self._show_reference = show_reference
        self._show_status = show_status
        self._refresh_mask_status = refresh_mask_status
        self._create_actions()
        self._create_menus()
        self.toolbar: QToolBar | None = None
        self._floating_pixels_toolbar: QToolBar | None = None
        self.build_toolbar()

    def connect_signals(self) -> None:
        """Refresh command presentation from public editor notifications."""
        self._canvas.catalogChanged.connect(self.handle_catalog_event)
        self._canvas.compositionChanged.connect(
            lambda _snapshot: self.handle_catalog_event(None)
        )
        self._canvas.compositionChanged.connect(
            lambda _snapshot: self.refresh_document_actions()
        )
        self._canvas.compositionSelectionChanged.connect(
            lambda _composition_id: self.refresh_tools()
        )
        self._canvas.catalogChanged.connect(lambda _event: self.refresh_tools())
        self._canvas.catalogSelectionChanged.connect(
            lambda _image_id: self.refresh_tools()
        )
        self._canvas.currentImageChanged.connect(lambda _image_id: self.refresh_tools())
        self._canvas.imageLoaded.connect(lambda _path: self.refresh_tools())
        self._canvas.comparisonChanged.connect(self.handle_comparison_changed)

    def prime(self) -> None:
        """Populate command state after the starter document is available."""
        self.handle_catalog_event(None)
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

        navigation_added = add_group([self.prev_image_action, self.next_image_action])
        compare_added = add_group(
            [
                self.compare_next_action,
                self.compose_contact_sheet_action,
                self.compare_flip_action,
                self.compare_clear_action,
            ]
        )
        mode_actions = self._tools.mode_actions()
        if (navigation_added or compare_added) and any(
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
        """Apply placeholder and feature policy to editor and mask actions."""
        self._tools.refresh_availability()
        mask_enabled = self._masks_available() and not self._canvas.placeholderActive()
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

    def handle_catalog_event(self, _event: object) -> None:
        """Refresh all command state derived from the catalog snapshot."""
        snapshot = build_catalog_snapshot(self._canvas)
        self.update_action_states(snapshot.image_count)
        self._catalog.handle_snapshot(snapshot)
        self.refresh_tools()

    def handle_comparison_changed(self, _state: object) -> None:
        """Refresh comparison commands after the comparison state changes."""
        self.update_action_states(len(self._canvas.imageIDs()))

    def update_action_states(self, count: int) -> None:
        """Enable gallery actions from image count and comparison state."""
        has_images = count > 0
        for action, base_enabled in self._gallery_actions:
            action.setEnabled(base_enabled and has_images)
        comparison_enabled = self._canvas.comparisonState().enabled
        self.compare_next_action.setEnabled(count > 1)
        self.compare_flip_action.setEnabled(comparison_enabled)
        self.compare_clear_action.setEnabled(comparison_enabled)
        if count < 2 and self._all_images_linked():
            self._canvas.setAllImagesLinked(False)
            self._show_status("Pan/zoom linking disabled.")
        self._catalog.maybe_auto_show(count)
        self.refresh_document_actions()

    def refresh_document_actions(self) -> None:
        """Enable saving only while an editable document is open."""
        self.save_document_action.setEnabled(
            self._canvas.editor.documents.current is not None
        )

    def set_delete_mask_enabled(self, enabled: bool) -> None:
        """Mirror derived mask presence into the optional delete command."""
        if self.delete_mask_action is not None:
            self.delete_mask_action.setEnabled(enabled)

    def _create_actions(self) -> None:
        """Create file, gallery, mask, view, and extension commands."""
        self.open_images_action = QAction("Open Images...", self._parent)
        self.open_images_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_images_action.triggered.connect(self._workspace.open_images_dialog)
        self.open_document_action = QAction("Open Document…", self._parent)
        self.open_document_action.setShortcut(QKeySequence("Ctrl+Alt+O"))
        self.open_document_action.triggered.connect(
            self._workspace.open_document_dialog
        )
        self.save_document_action = QAction("Save Document…", self._parent)
        self.save_document_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.save_document_action.triggered.connect(
            self._workspace.save_document_dialog
        )
        self.place_embedded_action = QAction("Place Embedded…", self._parent)
        self.place_embedded_action.triggered.connect(
            self._workspace.place_embedded_dialog
        )
        self.place_linked_action = QAction("Place Linked…", self._parent)
        self.place_linked_action.triggered.connect(self._workspace.place_linked_dialog)
        self.clear_action = QAction("Clear", self._parent)
        self.clear_action.triggered.connect(self._workspace.clear_gallery)
        self.prev_image_action = QAction("◀ Prev", self._parent)
        self.prev_image_action.setShortcut(Qt.Key_Left)
        self.prev_image_action.triggered.connect(lambda: self._workspace.step_image(-1))
        self.next_image_action = QAction("Next ▶", self._parent)
        self.next_image_action.setShortcut(Qt.Key_Right)
        self.next_image_action.triggered.connect(lambda: self._workspace.step_image(1))
        self.compare_next_action = QAction("Compare Next", self._parent)
        self.compare_next_action.triggered.connect(
            self._workspace.compare_with_next_image
        )
        self.compose_contact_sheet_action = QAction(
            "Compose Contact Sheet", self._parent
        )
        self.compose_contact_sheet_action.triggered.connect(
            self._workspace.compose_contact_sheet
        )
        self.compare_flip_action = QAction("Flip Compare", self._parent)
        self.compare_flip_action.triggered.connect(
            self._workspace.flip_compare_orientation
        )
        self.compare_clear_action = QAction("Clear Compare", self._parent)
        self.compare_clear_action.triggered.connect(self._workspace.clear_comparison)
        self._create_mask_actions()
        self.config_action = QAction("Config", self._parent)
        self.config_action.triggered.connect(self._configuration.open_dialog)
        self.catalog_panel_action = QAction(
            "Browser Panel", self._parent, checkable=True
        )
        self._catalog.bind_toggle_action(self.catalog_panel_action)
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
        self._gallery_actions = [
            (self.clear_action, True),
            (self.prev_image_action, True),
            (self.next_image_action, True),
            (self.compose_contact_sheet_action, True),
            (self.place_embedded_action, True),
            (self.place_linked_action, True),
        ]
        self._gallery_actions.extend(
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
        file_menu.addAction(self.open_document_action)
        file_menu.addAction(self.save_document_action)
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
        view_menu = menu_bar.addMenu("&View")
        view_menu.addAction(self.catalog_panel_action)
        view_menu.addAction(self.quick_reference_action)
        view_menu.addSeparator()
        view_menu.addAction(self.compare_next_action)
        view_menu.addAction(self.compose_contact_sheet_action)
        view_menu.addAction(self.compare_flip_action)
        view_menu.addAction(self.compare_clear_action)
        view_menu.addSeparator()
        self._configuration.build_diagnostics_menu(
            view_menu.addMenu("Diagnostics Overlay")
        )
        hooks_menu = menu_bar.addMenu("Hooks")
        hooks_menu.addAction(self.overlay_hook_action)
        hooks_menu.addAction(self.cursor_hook_action)
        hooks_menu.addAction(self.lens_hook_action)
        menu_bar.addAction(self.config_action)

    @staticmethod
    def _set_checked(action: QAction, checked: bool) -> None:
        """Set action state without invoking its connected command."""
        action.blockSignals(True)
        action.setChecked(checked)
        action.blockSignals(False)
