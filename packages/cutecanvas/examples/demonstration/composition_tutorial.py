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
"""Teach a composition-and-layer tree owned by the host interface.

CuteCanvas supplies snapshots and commands. This controller turns those values
into tree rows, manages the dock's presentation, and opens focused property
dialogs without copying composition state.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from cutecanvas import CuteCanvas
from demonstration.composition_properties_dialog import (
    CompositionPropertiesDialog,
)
from demonstration.compositions import CompositionDock
from demonstration.layer_properties_dialog import LayerPropertiesDialog
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget


class CompositionTutorialController:
    """Own the demo composition browser and its presentation lifecycle."""

    def __init__(
        self,
        canvas: CuteCanvas,
        parent: QWidget,
        *,
        container: QWidget,
        container_layout: QVBoxLayout,
        splitter: QSplitter,
        container_default_maximum: int,
        focus_requested: Callable[[str], None],
        show_status: Callable[[str], None],
    ) -> None:
        """Capture host presentation dependencies without duplicating editor state."""
        self._canvas = canvas
        self._parent = parent
        self._container = container
        self._container_layout = container_layout
        self._splitter = splitter
        self._container_default_maximum = container_default_maximum
        self._focus_requested = focus_requested
        self._show_status = show_status
        self._toggle_action: QAction | None = None
        self._toggle_sync = False
        self._user_override = False
        self._panel_width_hint: int | None = None
        self._layer_properties_dialog: LayerPropertiesDialog | None = None
        self._composition_properties_dialog: CompositionPropertiesDialog | None = None
        self.dock: CompositionDock | None = None

    def build(self) -> None:
        """Create or replace the browser using only the public canvas facade."""
        if self.dock is not None:
            try:
                self.dock.visibilityChanged.disconnect(self.sync_toggle)
            except (TypeError, RuntimeError):
                pass
            self._container_layout.removeWidget(self.dock)
            self.dock.setParent(None)
            self.dock.deleteLater()
        self.dock = CompositionDock(
            self._canvas,
            on_focus_requested=self._focus_requested,
            set_status=self._show_status,
            parent=self._container,
        )
        self.dock.visibilityChanged.connect(self.sync_toggle)
        self.dock.layerPropertiesRequested.connect(self.open_layer_properties)
        self.dock.compositionPropertiesRequested.connect(
            self.open_composition_properties
        )
        self._panel_width_hint = min(max(self.dock.panelWidthHint(), 260), 320)
        self._container_layout.addWidget(self.dock)
        self.dock.hide()
        self._apply_width_constraints(False)

    def bind_toggle_action(self, action: QAction) -> None:
        """Connect the host View-menu action to browser visibility."""
        if self._toggle_action is not None:
            try:
                self._toggle_action.toggled.disconnect(self.handle_toggled)
            except (TypeError, RuntimeError):
                pass
        self._toggle_action = action
        action.toggled.connect(self.handle_toggled)

    def refresh_selection(self) -> None:
        """Refresh browser highlighting after a host tool-policy change."""
        if self.dock is not None:
            self.dock.refresh_selection()

    def show_initially(self) -> None:
        """Reveal the browser for the tutorial's starter composition."""
        self._toggle_sync = True
        try:
            if self._toggle_action is not None:
                self._toggle_action.setChecked(True)
        finally:
            self._toggle_sync = False
        self.set_visible(True)

    def set_visible(self, visible: bool) -> None:
        """Set browser visibility without treating it as user preference."""
        self._apply_visibility(visible, user_initiated=False)

    def handle_toggled(self, expanded: bool) -> None:
        """Apply a deliberate host-user visibility change."""
        if self._toggle_sync:
            return
        self._apply_visibility(expanded, user_initiated=True)
        self._show_status("Browser shown." if expanded else "Browser hidden.")

    def sync_toggle(self, visible: bool) -> None:
        """Mirror dock visibility without changing the user's preference."""
        if not self._toggle_sync:
            self._apply_visibility(visible, user_initiated=False)

    def maybe_auto_show(self, count: int, *, force: bool = False) -> None:
        """Reveal useful multi-image or mask structure unless the user opted out."""
        action = self._toggle_action
        if action is None or ((not force and count < 2) or action.isChecked()):
            return
        if not self._user_override:
            self._apply_visibility(True, user_initiated=False)

    def open_layer_properties(
        self,
        _composition_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> None:
        """Open focused properties for the tree-selected active layer."""
        scene = self._canvas.currentScene()
        if scene is None:
            return
        if self._layer_properties_dialog is not None:
            self._layer_properties_dialog.close()
            self._layer_properties_dialog.deleteLater()
        dialog = LayerPropertiesDialog(
            self._canvas,
            scene.scene_id,
            layer_id,
            self._parent,
            show_status=self._show_status,
        )
        dialog.finished.connect(self._clear_layer_properties_dialog)
        self._layer_properties_dialog = dialog
        dialog.open()

    def open_composition_properties(self, composition_id: uuid.UUID) -> None:
        """Open focused policy properties for one composition."""
        if self._composition_properties_dialog is not None:
            self._composition_properties_dialog.close()
            self._composition_properties_dialog.deleteLater()
        dialog = CompositionPropertiesDialog(
            self._canvas,
            composition_id,
            self._parent,
            show_status=self._show_status,
        )
        dialog.finished.connect(self._clear_composition_properties_dialog)
        self._composition_properties_dialog = dialog
        dialog.open()

    def _apply_visibility(self, visible: bool, *, user_initiated: bool) -> None:
        """Apply panel visibility and splitter constraints atomically."""
        if self.dock is None:
            return
        if user_initiated:
            self._user_override = True
        self._toggle_sync = True
        try:
            if self._toggle_action is not None:
                self._toggle_action.blockSignals(True)
                self._toggle_action.setChecked(visible)
                self._toggle_action.blockSignals(False)
            self._apply_width_constraints(visible)
            self.dock.setVisible(visible)
            self._container.setVisible(visible)
            if visible:
                self._sync_splitter_width()
        finally:
            self._toggle_sync = False

    def _apply_width_constraints(self, visible: bool) -> None:
        """Keep the browser compact while allowing deliberate expansion."""
        width = self._panel_width_hint
        if width is None:
            return
        self._container.setMinimumWidth(width if visible else 0)
        self._container.setMaximumWidth(
            self._container_default_maximum if visible else width
        )

    def _sync_splitter_width(self) -> None:
        """Give the browser its readable width without starving the canvas."""
        width = self._panel_width_hint
        if width is None:
            return
        total = sum(self._splitter.sizes())
        if total <= 0:
            total = max(self._parent.width(), width * 2)
        total = max(total, width + 1)
        self._splitter.setSizes([width, max(total - width, 1)])

    def _clear_layer_properties_dialog(self, _result: int) -> None:
        """Release the completed layer-properties modal."""
        dialog = self._layer_properties_dialog
        self._layer_properties_dialog = None
        if dialog is not None:
            dialog.deleteLater()

    def _clear_composition_properties_dialog(self, _result: int) -> None:
        """Release the completed composition-properties modal."""
        dialog = self._composition_properties_dialog
        self._composition_properties_dialog = None
        if dialog is not None:
            dialog.deleteLater()
