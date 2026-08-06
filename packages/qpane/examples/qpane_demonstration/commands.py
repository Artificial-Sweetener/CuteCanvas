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
"""Teach a complete but restrained viewer command shell over QPane."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QActionGroup, QColor, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QToolBar,
    QWidget,
)
from qpane import LayerPresentationStyle, QPane, RenderScene

from .catalog import CatalogPanel
from .configuration import ViewerSettingsDialog
from .extensions import draw_viewer_frame
from .scenes import ViewerSceneController
from .status import ViewerStatusBar
from .workspace import ViewerWorkspaceController

_INSPECTION_MODE = "inspect"
_FRAME_OVERLAY = "viewer-frame"


class ViewerCommandController:
    """Own viewer actions, menus, toolbars, and derived presentation state."""

    def __init__(
        self,
        pane: QPane,
        parent: QMainWindow,
        *,
        workspace: ViewerWorkspaceController,
        scenes: ViewerSceneController,
        catalog_panel: CatalogPanel,
        status: ViewerStatusBar,
        catalog_container: QWidget,
        splitter: QSplitter,
    ) -> None:
        """Build commands around explicit public viewer collaborators."""
        self._pane = pane
        self._parent = parent
        self._workspace = workspace
        self._scenes = scenes
        self._catalog = pane.catalog()
        self._catalog_panel = catalog_panel
        self._status = status
        self._catalog_container = catalog_container
        self._splitter = splitter
        self._catalog_user_override = False
        self._layer_highlight_id: uuid.UUID | None = None
        self._create_actions()
        self._create_menus()
        self._build_toolbar()

    def connect_signals(self) -> None:
        """Wire public state changes to their focused host presenters."""
        self._catalog.selectionChanged.connect(self._workspace.show_catalog_entry)
        self._catalog_panel.currentEntryReactivated.connect(
            self._workspace.reactivate_catalog_entry
        )
        self._catalog.changed.connect(self._workspace.handle_catalog_changed)
        self._scenes.presentationChanged.connect(
            lambda _presentation: self.update_action_states()
        )
        self._pane.zoomChanged.connect(self._status.set_zoom)
        self._pane.sceneChanged.connect(self._handle_scene_changed)
        self._pane.controlModeChanged.connect(self._sync_control_mode)
        self._pane.dragOutRequested.connect(
            lambda _event: self._status.showMessage("Image drag-out started")
        )
        self._pane.diagnosticsOverlayToggled.connect(self.diagnostics_action.setChecked)
        self._pane.diagnosticsDomainToggled.connect(self._sync_diagnostics_domain)
        self._pane.linkGroupsChanged.connect(self._sync_link_views)
        self._pane.placeholderChanged.connect(self._handle_placeholder_changed)

    def prime(self) -> None:
        """Apply initial visibility and command state for an empty viewer."""
        self.set_catalog_visible(False, user_requested=False)
        self.update_action_states()

    def reveal_catalog_automatically(self) -> None:
        """Reveal multi-image navigation unless the user explicitly hid it."""
        if not self._catalog_user_override:
            self.set_catalog_visible(True, user_requested=False)

    def update_action_states(self) -> None:
        """Enable commands only when current catalog state supports them."""
        count = len(self._catalog.entries)
        has_image = count > 0
        for action in (
            self.copy_action,
            self.remove_current_action,
            self.clear_action,
            self.previous_action,
            self.next_action,
            self.contact_sheet_action,
        ):
            action.setEnabled(has_image)
        self.compare_next_action.setEnabled(count > 1)
        self.flip_compare_action.setEnabled(self._scenes.comparison_active)
        self.clear_compare_action.setEnabled(self._scenes.comparison_active)
        scene_active = self._pane.scene() is not None
        self.fit_action.setEnabled(scene_active)
        self.actual_size_action.setEnabled(scene_active)
        self.inspect_action.setEnabled(scene_active)

    def set_catalog_visible(self, visible: bool, *, user_requested: bool) -> None:
        """Synchronize splitter visibility and its checked menu command."""
        if user_requested:
            self._catalog_user_override = True
        self._catalog_container.setVisible(visible)
        self.catalog_panel_action.blockSignals(True)
        self.catalog_panel_action.setChecked(visible)
        self.catalog_panel_action.blockSignals(False)
        if visible:
            self._splitter.setSizes([280, max(self._parent.width() - 280, 1)])

    def apply_zoom_preset(self, preset: str) -> None:
        """Apply the status bar's selected fit or native-pixel preset."""
        if preset == "actual":
            self._pane.setZoom1To1()
        else:
            self._pane.setZoomFit()

    def show_canvas_menu(self, point: QPoint) -> None:
        """Offer common viewer commands from the canvas context menu."""
        menu = QMenu(self._parent)
        menu.addAction(self.open_images_action)
        if self._pane.scene() is not None:
            menu.addSeparator()
            menu.addAction(self.copy_action)
            menu.addAction(self.fit_action)
            menu.addAction(self.actual_size_action)
        menu.exec(self._pane.mapToGlobal(point))

    def _create_actions(self) -> None:
        """Create navigation, comparison, view, and SDK lesson commands."""
        self.open_images_action = QAction("Open Images…", self._parent)
        self.open_images_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_images_action.triggered.connect(self._workspace.open_images)
        self.remove_current_action = QAction("Remove Current", self._parent)
        self.remove_current_action.setShortcut(QKeySequence("Backspace"))
        self.remove_current_action.triggered.connect(self._workspace.remove_current)
        self.clear_action = QAction("Clear", self._parent)
        self.clear_action.triggered.connect(self._workspace.clear_catalog)
        self.copy_action = QAction("Copy Image", self._parent)
        self.copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        self.copy_action.triggered.connect(self._workspace.copy_current_image)
        self.previous_action = QAction("◀ Prev", self._parent)
        self.previous_action.setShortcut(QKeySequence(Qt.Key.Key_Left))
        self.previous_action.triggered.connect(self._workspace.previous_image)
        self.next_action = QAction("Next ▶", self._parent)
        self.next_action.setShortcut(QKeySequence(Qt.Key.Key_Right))
        self.next_action.triggered.connect(self._workspace.next_image)
        self.compare_next_action = QAction("Compare Next", self._parent)
        self.compare_next_action.triggered.connect(self._workspace.compare_next)
        self.contact_sheet_action = QAction("Compose Contact Sheet", self._parent)
        self.contact_sheet_action.triggered.connect(
            self._workspace.compose_contact_sheet
        )
        self.flip_compare_action = QAction("Flip Compare", self._parent)
        self.flip_compare_action.triggered.connect(self._workspace.flip_compare)
        self.clear_compare_action = QAction("Clear Compare", self._parent)
        self.clear_compare_action.triggered.connect(self._workspace.clear_compare)
        self.pan_action = QAction("Pan/Zoom", self._parent, checkable=True)
        self.pan_action.setChecked(True)
        self.pan_action.triggered.connect(
            lambda: self._pane.setControlMode(self._pane.CONTROL_MODE_PANZOOM)
        )
        self.cursor_action = QAction("Cursor", self._parent, checkable=True)
        self.cursor_action.triggered.connect(
            lambda: self._pane.setControlMode(self._pane.CONTROL_MODE_CURSOR)
        )
        self.inspect_action = QAction("Inspect", self._parent, checkable=True)
        self.inspect_action.triggered.connect(
            lambda: self._pane.setControlMode(_INSPECTION_MODE)
        )
        mode_actions = QActionGroup(self._parent)
        mode_actions.setExclusive(True)
        for action in (self.pan_action, self.cursor_action, self.inspect_action):
            mode_actions.addAction(action)
        self._mode_actions = mode_actions
        self.fit_action = QAction("Fit", self._parent)
        self.fit_action.setShortcut(QKeySequence("Ctrl+0"))
        self.fit_action.triggered.connect(
            lambda _checked=False: self._pane.setZoomFit()
        )
        self.actual_size_action = QAction("1:1", self._parent)
        self.actual_size_action.setShortcut(QKeySequence("Ctrl+1"))
        self.actual_size_action.triggered.connect(
            lambda _checked=False: self._pane.setZoom1To1()
        )
        self.catalog_panel_action = QAction(
            "Catalog Panel", self._parent, checkable=True
        )
        self.catalog_panel_action.toggled.connect(
            lambda visible: self.set_catalog_visible(visible, user_requested=True)
        )
        self.settings_action = QAction("Viewer Settings…", self._parent)
        self.settings_action.triggered.connect(self._show_settings)
        self.link_views_action = QAction(
            "Link Image Views", self._parent, checkable=True
        )
        self.link_views_action.toggled.connect(self._pane.setAllImagesLinked)
        self.diagnostics_action = QAction(
            "Diagnostics Overlay", self._parent, checkable=True
        )
        self.diagnostics_action.toggled.connect(self._pane.setDiagnosticsOverlayEnabled)
        self.diagnostics_domain_actions: dict[str, QAction] = {}
        for domain in self._pane.diagnosticsDomains():
            action = QAction(domain.title(), self._parent, checkable=True)
            action.toggled.connect(
                lambda enabled, name=domain: self._pane.setDiagnosticsDomainEnabled(
                    name, enabled
                )
            )
            self.diagnostics_domain_actions[domain] = action
        self.sdk_scene_action = QAction("Rendering SDK Scene", self._parent)
        self.sdk_scene_action.triggered.connect(self._workspace.show_sdk_scene)
        self.quick_reference_action = QAction("Quick Reference", self._parent)
        self.quick_reference_action.triggered.connect(self._show_quick_reference)
        self.frame_overlay_action = QAction(
            "Viewer Frame Overlay", self._parent, checkable=True
        )
        self.frame_overlay_action.toggled.connect(self._toggle_frame_overlay)
        self.layer_highlight_action = QAction(
            "Highlight Top Layer", self._parent, checkable=True
        )
        self.layer_highlight_action.toggled.connect(self._toggle_layer_highlight)

    def _create_menus(self) -> None:
        """Arrange the viewer commands in restrained, tutorial-friendly menus."""
        file_menu = self._parent.menuBar().addMenu("&File")
        file_menu.addAction(self.open_images_action)
        file_menu.addAction(self.copy_action)
        file_menu.addAction(self.remove_current_action)
        file_menu.addSeparator()
        file_menu.addAction(self.clear_action)
        file_menu.addSeparator()
        file_menu.addAction("Exit").triggered.connect(self._parent.close)
        view_menu = self._parent.menuBar().addMenu("&View")
        view_menu.addAction(self.catalog_panel_action)
        view_menu.addAction(self.settings_action)
        view_menu.addAction(self.quick_reference_action)
        view_menu.addSeparator()
        view_menu.addAction(self.fit_action)
        view_menu.addAction(self.actual_size_action)
        view_menu.addSeparator()
        view_menu.addAction(self.diagnostics_action)
        diagnostics_menu = view_menu.addMenu("Diagnostics Detail")
        diagnostics_menu.addActions(list(self.diagnostics_domain_actions.values()))
        compare_menu = self._parent.menuBar().addMenu("&Compare")
        compare_menu.addAction(self.compare_next_action)
        compare_menu.addAction(self.flip_compare_action)
        compare_menu.addAction(self.clear_compare_action)
        compare_menu.addSeparator()
        compare_menu.addAction(self.link_views_action)
        scene_menu = self._parent.menuBar().addMenu("&Scene")
        scene_menu.addAction(self.contact_sheet_action)
        scene_menu.addAction(self.sdk_scene_action)
        extensions_menu = self._parent.menuBar().addMenu("&Extensions")
        extensions_menu.addAction(self.frame_overlay_action)
        extensions_menu.addAction(self.layer_highlight_action)
        extensions_menu.addAction(self.inspect_action)

    def _build_toolbar(self) -> None:
        """Build the recognizable compact vertical text toolbar."""
        toolbar = QToolBar("Tools", self._parent)
        toolbar.setObjectName("viewerTools")
        toolbar.setMovable(False)
        toolbar.setOrientation(Qt.Orientation.Vertical)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._parent.addToolBar(Qt.ToolBarArea.LeftToolBarArea, toolbar)
        toolbar.addActions([self.previous_action, self.next_action])
        toolbar.addSeparator()
        toolbar.addActions(
            [
                self.compare_next_action,
                self.contact_sheet_action,
                self.flip_compare_action,
                self.clear_compare_action,
            ]
        )
        toolbar.addSeparator()
        toolbar.addActions(
            [
                self.cursor_action,
                self.pan_action,
                self.inspect_action,
                self.fit_action,
                self.actual_size_action,
            ]
        )
        self.toolbar = toolbar

    def _show_quick_reference(self, _checked: bool = False) -> None:
        """Show concise viewer navigation and scene shortcuts."""
        QMessageBox.information(
            self._parent,
            "QPane Quick Reference",
            "Ctrl+O   Open images\n"
            "Ctrl+C   Copy current image\n"
            "← / →    Previous / next image\n"
            "Drag      Pan\n"
            "Wheel     Zoom around pointer\n"
            "Ctrl+0    Fit scene\n"
            "Ctrl+1    Actual pixels\n"
            "Backspace Remove current image",
        )

    def _show_settings(self, _checked: bool = False) -> None:
        """Edit detached viewer settings and apply them through the facade."""
        dialog = ViewerSettingsDialog(
            self._pane.settings,
            self._pane.diagnosticsDomains(),
            self._parent,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._pane.applySettings(dialog.config(self._pane.settings))
        except (TypeError, ValueError) as exc:
            QMessageBox.warning(self._parent, "Invalid viewer settings", str(exc))
            return
        self._status.showMessage("Viewer settings applied")

    def _sync_diagnostics_domain(self, domain: str, enabled: bool) -> None:
        """Keep diagnostics detail aligned with direct configuration."""
        action = self.diagnostics_domain_actions.get(domain)
        if action is not None:
            action.setChecked(enabled)

    def _sync_link_views(self) -> None:
        """Reflect whether the catalog forms one linked view group."""
        all_ids = {entry.entry_id for entry in self._catalog.entries}
        linked = any(
            set(group.members) == all_ids for group in self._pane.linkedImageGroups()
        )
        self.link_views_action.blockSignals(True)
        self.link_views_action.setChecked(bool(all_ids) and linked)
        self.link_views_action.blockSignals(False)

    def _handle_placeholder_changed(self, state: object) -> None:
        """Surface placeholder failures without intrusive modal UI."""
        error = getattr(state, "error", None)
        if error:
            self._status.showMessage(f"Placeholder unavailable: {error}")

    def _toggle_frame_overlay(self, enabled: bool) -> None:
        """Install or remove the public content-overlay example."""
        if enabled:
            self._pane.registerOverlay(_FRAME_OVERLAY, draw_viewer_frame)
            self._status.showMessage("Viewer frame overlay enabled")
        else:
            self._pane.unregisterOverlay(_FRAME_OVERLAY)
            self._status.showMessage("Viewer frame overlay hidden")

    def _toggle_layer_highlight(self, enabled: bool) -> None:
        """Demonstrate source-neutral transient layer treatment."""
        self._refresh_layer_highlight()
        self._status.showMessage(
            "Top rendered layer highlighted"
            if enabled and self._layer_highlight_id is not None
            else "Layer highlight hidden"
        )

    def _refresh_layer_highlight(self) -> None:
        """Retarget the optional lesson effect after scene changes."""
        if self._layer_highlight_id is not None:
            self._pane.removeLayerPresentationEffect(self._layer_highlight_id)
            self._layer_highlight_id = None
        if not self.layer_highlight_action.isChecked():
            return
        scene = self._pane.scene()
        layer = next(
            (
                candidate
                for candidate in reversed(scene.layers if scene is not None else ())
                if candidate.visible and candidate.opacity > 0.0
            ),
            None,
        )
        if scene is None or layer is None:
            return
        self._layer_highlight_id = self._pane.addLayerPresentationEffect(
            scene.scene_id,
            layer.layer_id,
            LayerPresentationStyle.outline(
                QColor(84, 180, 238),
                width=2.0,
                opacity=0.9,
            ),
        )

    def _sync_control_mode(self, mode: str) -> None:
        """Keep compact mode actions aligned with QPane state."""
        action = {
            self._pane.CONTROL_MODE_PANZOOM: self.pan_action,
            self._pane.CONTROL_MODE_CURSOR: self.cursor_action,
            _INSPECTION_MODE: self.inspect_action,
        }.get(mode)
        if action is not None:
            action.setChecked(True)

    def _handle_scene_changed(self, scene: RenderScene | None) -> None:
        """Reflect the public scene canvas in status and presentation effects."""
        self._refresh_layer_highlight()
        if scene is None:
            self._status.set_image_size(None, None)
        else:
            self._status.set_image_size(
                round(scene.canvas.width()),
                round(scene.canvas.height()),
            )
        self._status.set_zoom(self._pane.currentZoom())
