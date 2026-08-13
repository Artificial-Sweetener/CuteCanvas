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
"""Teach a compact status bar driven entirely by public CuteCanvas state.

The controller owns presentation-only state: labels, zoom text editing, and
non-modal progress messages. It observes the editor and issues public zoom
commands, but never owns document, layer, mask, or renderer state.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from math import isclose
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QStatusBar,
    QToolButton,
    QWidget,
)

from cutecanvas import CuteCanvas


class StatusTutorialController:
    """Own the demo status bar and its observational editor readouts."""

    def __init__(
        self,
        canvas: CuteCanvas,
        parent: QWidget,
        *,
        masks_available: Callable[[], bool],
        show_mask_history: bool,
        show_sam: bool,
    ) -> None:
        """Build status widgets for the enabled editor capabilities."""
        self._canvas = canvas
        self._masks_available = masks_available
        self._sam_status_auto_hide = False
        self.bar = QStatusBar(parent)
        self._sam_label: QLabel | None = None
        self._mask_stack_label: QLabel | None = None
        if show_sam:
            self._sam_label = QLabel("SAM: --")
            self._sam_label.setObjectName("samStatusLabel")
            self._sam_label.setStyleSheet("padding: 0 6px;")
            self.bar.addPermanentWidget(self._sam_label)
        if show_mask_history:
            self._mask_stack_label = QLabel("Undo: 0 / Redo: 0")
            self._mask_stack_label.setObjectName("maskStackStatusLabel")
            self._mask_stack_label.setStyleSheet("padding: 0 6px;")
            self.bar.addPermanentWidget(self._mask_stack_label)
        self._image_size_label = QLabel("-- x --px")
        self._image_size_label.setObjectName("imageSizeStatusLabel")
        self._image_size_label.setStyleSheet("padding: 0 6px;")
        self.bar.addPermanentWidget(self._image_size_label)
        self._zoom_toggle_button = self._build_zoom_toggle(parent)
        self.zoom_input = self._build_zoom_input(parent)

    def show_message(self, message: str, timeout_ms: int = 0) -> None:
        """Present one non-modal application message."""
        self.bar.showMessage(message, timeout_ms)

    def connect_signals(self) -> None:
        """Connect status readouts to public editor signals once."""
        self._canvas.zoomChanged.connect(self.update_zoom)
        self._canvas.compositionSelectionChanged.connect(self.handle_document_selection)
        self._canvas.sceneChanged.connect(lambda _scene: self.update_image_size())
        self._canvas.maskSaved.connect(self.handle_mask_saved)
        if self._mask_stack_label is not None:
            self._canvas.maskUndoStackChanged.connect(self.update_mask_stack)
        if self._sam_label is not None:
            self._canvas.samCheckpointStatusChanged.connect(
                self.handle_sam_checkpoint_status
            )
            self._canvas.samCheckpointProgress.connect(
                self.handle_sam_checkpoint_progress
            )
        self._canvas.placedAssetRequestCompleted.connect(
            self.handle_placed_asset_completion
        )

    def prime(self) -> None:
        """Populate every readout from the editor's current state."""
        try:
            zoom = self._canvas.currentZoom()
        except RuntimeError:  # pragma: no cover - deleted Qt object during teardown
            zoom = 1.0
        self.update_zoom(zoom)
        self.resize_zoom_input()
        self.resize_zoom_toggle()
        self.update_image_size()
        self.update_mask_stack()
        self._prime_sam_status()

    def handle_mask_saved(self, path: str, mask_id: str) -> None:
        """Confirm successful mask persistence without blocking the editor."""
        self.show_message(f"Autosaved mask {mask_id} to {path}")

    def update_image_size(self) -> None:
        """Display current raster dimensions or an empty placeholder."""
        scene = self._canvas.currentScene()
        if scene is None or scene.bounds.isEmpty():
            self._image_size_label.setText("-- x --px")
        else:
            size = scene.bounds.size()
            self._image_size_label.setText(
                f"{round(size.width())} x {round(size.height())}px"
            )

    def update_zoom(self, zoom: float) -> None:
        """Mirror settled zoom while preserving active text editing."""
        if self.zoom_input.isReadOnly():
            self.zoom_input.setText(self._format_zoom_percent(zoom))
        if isclose(zoom, 1.0, rel_tol=0.0, abs_tol=1e-3):
            self._zoom_toggle_button.setText("Set Fit")
            self._zoom_toggle_button.setToolTip("Fit the image to the viewport.")
        else:
            self._zoom_toggle_button.setText("Set 1:1")
            self._zoom_toggle_button.setToolTip("Snap to native 1:1 pixel scale.")

    def resize_zoom_input(self) -> None:
        """Reserve enough width for the largest ordinary percentage label."""
        metrics = self.zoom_input.fontMetrics()
        margins = self.zoom_input.textMargins()
        self.zoom_input.setFixedWidth(
            metrics.horizontalAdvance("1000.0%") + margins.left() + margins.right() + 12
        )

    def resize_zoom_toggle(self) -> None:
        """Keep the fit/native toggle stable while its label changes."""
        width = self._zoom_toggle_button.fontMetrics().horizontalAdvance("Set 1:1")
        self._zoom_toggle_button.setFixedWidth(width + 16)

    def apply_zoom_input(self) -> None:
        """Parse a percentage and apply it through the public viewport facade."""
        raw = self.zoom_input.text().strip()
        if not raw:
            self._reset_zoom_input()
            self.exit_zoom_edit()
            return
        if raw.endswith("%"):
            raw = raw[:-1].strip()
        try:
            percent = float(raw)
        except ValueError:
            self.show_message("Enter zoom as a percent (for example: 125%).")
            self._reset_zoom_input()
            self.exit_zoom_edit()
            return
        if percent <= 0:
            self.show_message("Zoom percent must be greater than zero.")
            self._reset_zoom_input()
            self.exit_zoom_edit()
            return
        self._canvas.applyZoom(percent / 100.0)
        self.zoom_input.setText(self._format_zoom_percent(self._canvas.currentZoom()))
        self.exit_zoom_edit()

    def enter_zoom_edit(self) -> None:
        """Turn the passive zoom readout into a focused text editor."""
        self.zoom_input.setReadOnly(False)
        self.zoom_input.setFrame(True)
        self.zoom_input.setStyleSheet("")
        self.zoom_input.setCursor(Qt.CursorShape.IBeamCursor)
        self.zoom_input.setFocus(Qt.FocusReason.MouseFocusReason)
        self.zoom_input.selectAll()

    def exit_zoom_edit(self) -> None:
        """Return the zoom field to its compact display presentation."""
        self.zoom_input.setReadOnly(True)
        self.zoom_input.setFrame(False)
        self.zoom_input.setStyleSheet(
            "QLineEdit#zoomPercentInput { background: transparent; border: none; }"
        )
        self.zoom_input.setCursor(Qt.CursorShape.ArrowCursor)

    def update_mask_stack(self, mask_id: uuid.UUID | None = None) -> None:
        """Display chronological mask undo and redo depth."""
        label = self._mask_stack_label
        if label is None:
            return
        if not self._masks_available():
            label.setText("Undo: -- / Redo: --")
            return
        active_mask_id = mask_id or self._canvas.activeMaskID()
        if active_mask_id is None:
            label.setText("Undo: 0 / Redo: 0")
            return
        try:
            state = self._canvas.getMaskUndoState(active_mask_id)
        except (RuntimeError, ValueError):
            state = None
        if state is None:
            label.setText("Undo: 0 / Redo: 0")
        else:
            label.setText(f"Undo: {state.undo_depth} / Redo: {state.redo_depth}")

    def handle_document_selection(
        self,
        composition_id: uuid.UUID | None,
    ) -> None:
        """Describe document selection and refresh dependent readouts."""
        self.update_mask_stack()
        self.update_image_size()
        if composition_id is None:
            self.show_message("No document selected.")
            return
        entry = self._canvas.getCompositionSnapshot().compositions.get(composition_id)
        self.show_message(
            "Selected document."
            if entry is None or entry.title is None
            else f"Selected document: {entry.title}"
        )

    def handle_sam_checkpoint_status(self, status: str, path: Path) -> None:
        """Mirror SAM checkpoint lifecycle in one compact label."""
        normalized = status.strip().lower()
        if normalized == "downloading":
            text = "SAM: downloading"
            self._sam_status_auto_hide = True
        elif normalized == "ready":
            if not self._sam_status_auto_hide:
                return
            text = "SAM: ready"
        elif normalized in {"failed", "missing"}:
            text = f"SAM: {normalized}"
            self._sam_status_auto_hide = False
        else:
            text = f"SAM: {status}"
            self._sam_status_auto_hide = False
        self._set_sam_label(text, tooltip=str(path))
        if (
            normalized == "ready"
            and self._sam_status_auto_hide
            and self._sam_label is not None
        ):
            QTimer.singleShot(10000, self._sam_label.hide)

    def handle_sam_checkpoint_progress(
        self,
        downloaded: int,
        total: int | None,
    ) -> None:
        """Show checkpoint download bytes or a bounded percentage."""
        self._sam_status_auto_hide = True
        if total:
            percent = max(0.0, min(100.0, (downloaded / total) * 100.0))
            text = f"SAM: downloading {percent:.0f}%"
        else:
            text = f"SAM: downloading {self._format_bytes(downloaded)}"
        self._set_sam_label(text)

    def handle_placed_asset_completion(
        self,
        _request_id: uuid.UUID,
        scene_id: object,
        layer_id: object,
        succeeded: bool,
        message: str,
    ) -> None:
        """Select successful placed work and surface non-modal failures."""
        if not succeeded:
            self.show_message(f"Placed asset operation failed: {message}")
            return
        if isinstance(scene_id, uuid.UUID) and isinstance(layer_id, uuid.UUID):
            self._canvas.setSelectedLayer(scene_id, layer_id)
        current = self._canvas.currentScene()
        layer = (
            None
            if current is None
            else next(
                (
                    candidate
                    for candidate in current.layers
                    if candidate.layer_id == layer_id
                ),
                None,
            )
        )
        self.show_message(
            "Rasterization complete. The layer is ready for pixel editing."
            if layer is not None and layer.source_kind == "raster"
            else "Placed asset operation completed."
        )

    def _build_zoom_toggle(self, parent: QWidget) -> QToolButton:
        """Build the fit/native toggle and add it to the status bar."""
        container = QWidget(parent)
        container.setObjectName("zoomToggleContainer")
        container.setStyleSheet("padding: 0 6px;")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        button = QToolButton(container)
        button.setObjectName("zoomToggleButton")
        button.setAutoRaise(True)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        button.clicked.connect(self._toggle_zoom_target)
        layout.addWidget(button)
        self.bar.addPermanentWidget(container)
        return button

    def _build_zoom_input(self, parent: QWidget) -> QLineEdit:
        """Build the passive zoom readout and editable percentage field."""
        container = QWidget(parent)
        container.setObjectName("zoomStatusContainer")
        container.setStyleSheet("padding: 0 6px;")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        label = QLabel("Zoom:", container)
        label.setObjectName("zoomStatusLabel")
        label.setStyleSheet("padding-right: 2px;")
        layout.addWidget(label)
        field = QLineEdit(container)
        field.setObjectName("zoomPercentInput")
        field.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        field.setClearButtonEnabled(False)
        field.setReadOnly(True)
        field.setFrame(False)
        field.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        field.setStyleSheet(
            "QLineEdit#zoomPercentInput { background: transparent; border: none; }"
        )
        field.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        field.returnPressed.connect(self.apply_zoom_input)
        layout.addWidget(field)
        self.bar.addPermanentWidget(container)
        return field

    def _toggle_zoom_target(self) -> None:
        """Toggle between fit and native one-to-one zoom."""
        if isclose(self._canvas.currentZoom(), 1.0, rel_tol=0.0, abs_tol=1e-3):
            self._canvas.setZoomFit()
        else:
            self._canvas.setZoom1To1()

    def _reset_zoom_input(self) -> None:
        """Restore the zoom field from authoritative viewport state."""
        self.zoom_input.setText(self._format_zoom_percent(self._canvas.currentZoom()))

    def _prime_sam_status(self) -> None:
        """Populate optional SAM state without triggering model work."""
        if self._sam_label is None:
            return
        if not self._canvas.samFeatureAvailable():
            self._sam_label.setText("SAM: unavailable")
            return
        self._sam_label.setText(
            "SAM: ready" if self._canvas.samCheckpointReady() else "SAM: pending"
        )
        path = self._canvas.samCheckpointPath()
        if path is not None:
            self._sam_label.setToolTip(str(path))

    def _set_sam_label(self, text: str, tooltip: str | None = None) -> None:
        """Update the optional SAM label when installed."""
        if self._sam_label is None:
            return
        self._sam_label.setText(text)
        if tooltip is not None:
            self._sam_label.setToolTip(tooltip)

    @staticmethod
    def _format_zoom_percent(zoom: float) -> str:
        """Return one decimal percentage for a viewport zoom factor."""
        return f"{zoom * 100:.1f}%"

    @staticmethod
    def _format_bytes(value: int) -> str:
        """Return a compact byte count for progress presentation."""
        size = float(value)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                return f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}TB"
