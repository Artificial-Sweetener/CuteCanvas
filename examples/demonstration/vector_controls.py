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
"""Compact public-API vector creation controls for the demonstration host."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import replace

from cutecanvas import CuteCanvas, VectorShapeKind, VectorTextAlignment
from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QKeySequence
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFontComboBox,
    QLabel,
    QMenu,
    QToolBar,
    QToolButton,
)


class VectorControls(QObject):
    """Own the demo's intentional vector-layer and contextual tool controls."""

    def __init__(
        self,
        qpane: CuteCanvas,
        *,
        set_mode: Callable[[str], None],
        show_status: Callable[[str], None],
        parent: QObject,
    ) -> None:
        """Create public facade actions and subscribe to detached state."""
        super().__init__(parent)
        self._qpane = qpane
        self._set_mode = set_mode
        self._show_status = show_status
        self._toolbar: QToolBar | None = None
        self.add_layer_action = QAction("Add Vector Layer", self)
        self.add_layer_action.triggered.connect(self._add_layer)
        self.shape_action = QAction("Shape", self, checkable=True)
        self.shape_action.setShortcut(QKeySequence("U"))
        self.shape_action.triggered.connect(
            lambda: self._set_mode(CuteCanvas.CONTROL_MODE_VECTOR_SHAPE)
        )
        self.path_action = QAction("Path", self, checkable=True)
        self.path_action.setShortcut(QKeySequence("P"))
        self.path_action.triggered.connect(
            lambda: self._set_mode(CuteCanvas.CONTROL_MODE_VECTOR_PATH)
        )
        self.node_action = QAction("Edit Nodes", self, checkable=True)
        self.node_action.setShortcut(QKeySequence("A"))
        self.node_action.triggered.connect(
            lambda: self._set_mode(CuteCanvas.CONTROL_MODE_VECTOR_NODE)
        )
        self.text_action = QAction("Text", self, checkable=True)
        self.text_action.setShortcut(QKeySequence("T"))
        self.text_action.triggered.connect(
            lambda: self._set_mode(CuteCanvas.CONTROL_MODE_VECTOR_TEXT)
        )
        self.to_selection_action = QAction("To Selection", self)
        self.to_selection_action.triggered.connect(self._convert_to_selection)
        self.rasterize_action = QAction("Rasterize", self)
        self.rasterize_action.triggered.connect(self._rasterize)
        self.mask_below_action = QAction("Mask Layer Below", self)
        self.mask_below_action.triggered.connect(self._mask_layer_below)
        self.remove_mask_action = QAction("Remove Mask", self)
        self.remove_mask_action.triggered.connect(self._remove_mask)
        group = QActionGroup(self)
        group.setExclusive(True)
        group.addAction(self.shape_action)
        group.addAction(self.path_action)
        group.addAction(self.node_action)
        group.addAction(self.text_action)
        qpane.vectorToolOptionsChanged.connect(self.refresh)
        qpane.vectorTextEditChanged.connect(self.refresh)
        qpane.selectedLayerChanged.connect(self.refresh)
        qpane.sceneChanged.connect(self.refresh)
        qpane.vectorRequestCompleted.connect(self._handle_request_completed)

    def add_tool_button(self, toolbar: QToolBar) -> QToolButton:
        """Add one last-used Shape/Path split control to the tools toolbar."""
        menu = QMenu(toolbar)
        menu.addAction(self.shape_action)
        menu.addAction(self.path_action)
        menu.addAction(self.node_action)
        menu.addAction(self.text_action)
        button = QToolButton(toolbar)
        button.setPopupMode(QToolButton.MenuButtonPopup)
        button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        button.setDefaultAction(self.shape_action)
        button.setMenu(menu)
        self.shape_action.triggered.connect(
            lambda: button.setDefaultAction(self.shape_action)
        )
        self.path_action.triggered.connect(
            lambda: button.setDefaultAction(self.path_action)
        )
        self.node_action.triggered.connect(
            lambda: button.setDefaultAction(self.node_action)
        )
        self.text_action.triggered.connect(
            lambda: button.setDefaultAction(self.text_action)
        )
        toolbar.addWidget(button)
        return button

    def build_context_toolbar(self, toolbar: QToolBar) -> None:
        """Populate one compact contextual vector style toolbar."""
        self._toolbar = toolbar
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        toolbar.addWidget(QLabel(" Vector ", toolbar))
        self._shape_combo = QComboBox(toolbar)
        self._shape_combo.addItem("Rectangle", VectorShapeKind.RECTANGLE)
        self._shape_combo.addItem("Ellipse", VectorShapeKind.ELLIPSE)
        self._shape_combo.currentIndexChanged.connect(self._set_shape)
        toolbar.addWidget(self._shape_combo)
        self._fill_button = QToolButton(toolbar)
        self._fill_button.setText("Fill")
        self._fill_button.clicked.connect(self._choose_fill)
        toolbar.addWidget(self._fill_button)
        self._stroke_button = QToolButton(toolbar)
        self._stroke_button.setText("Stroke")
        self._stroke_button.clicked.connect(self._choose_stroke)
        toolbar.addWidget(self._stroke_button)
        toolbar.addWidget(QLabel(" Width ", toolbar))
        self._width = QDoubleSpinBox(toolbar)
        self._width.setRange(0.0, 1000.0)
        self._width.setDecimals(1)
        self._width.setSingleStep(0.5)
        self._width.valueChanged.connect(self._set_width)
        toolbar.addWidget(self._width)
        self._font = QFontComboBox(toolbar)
        self._font.setToolTip("Text font family")
        self._font.currentFontChanged.connect(self._set_text_family)
        toolbar.addWidget(self._font)
        self._font_size = QDoubleSpinBox(toolbar)
        self._font_size.setRange(1.0, 1000.0)
        self._font_size.setDecimals(1)
        self._font_size.setSuffix(" pt")
        self._font_size.setToolTip("Text size")
        self._font_size.valueChanged.connect(self._set_text_size)
        toolbar.addWidget(self._font_size)
        self._bold = QAction("Bold", self, checkable=True)
        self._bold.triggered.connect(self._set_text_bold)
        toolbar.addAction(self._bold)
        self._italic = QAction("Italic", self, checkable=True)
        self._italic.triggered.connect(self._set_text_italic)
        toolbar.addAction(self._italic)
        self._alignment = QComboBox(toolbar)
        self._alignment.addItem("Left", VectorTextAlignment.LEFT)
        self._alignment.addItem("Center", VectorTextAlignment.CENTER)
        self._alignment.addItem("Right", VectorTextAlignment.RIGHT)
        self._alignment.addItem("Justify", VectorTextAlignment.JUSTIFY)
        self._alignment.currentIndexChanged.connect(self._set_text_alignment)
        toolbar.addWidget(self._alignment)
        self._commit_text = QAction("Commit Text", self)
        self._commit_text.triggered.connect(self._qpane.commitVectorTextEdit)
        toolbar.addAction(self._commit_text)
        self._cancel_text = QAction("Cancel", self)
        self._cancel_text.triggered.connect(self._qpane.cancelVectorTextEdit)
        toolbar.addAction(self._cancel_text)
        self._text_to_paths = QAction("Convert to Paths", self)
        self._text_to_paths.triggered.connect(self._convert_text_to_paths)
        toolbar.addAction(self._text_to_paths)
        toolbar.addSeparator()
        toolbar.addAction(self.to_selection_action)
        toolbar.addAction(self.rasterize_action)
        toolbar.addAction(self.mask_below_action)
        toolbar.addAction(self.remove_mask_action)
        self.refresh()

    def populate_layer_menu(self, menu: QMenu) -> None:
        """Add vector creation at the normal layer-authoring location."""
        menu.addAction(self.add_layer_action)

    def sync_mode(self, mode: str) -> None:
        """Synchronize action state and contextual toolbar visibility."""
        self.shape_action.setChecked(mode == CuteCanvas.CONTROL_MODE_VECTOR_SHAPE)
        self.path_action.setChecked(mode == CuteCanvas.CONTROL_MODE_VECTOR_PATH)
        self.node_action.setChecked(mode == CuteCanvas.CONTROL_MODE_VECTOR_NODE)
        self.text_action.setChecked(mode == CuteCanvas.CONTROL_MODE_VECTOR_TEXT)
        if self._toolbar is not None:
            self._toolbar.setVisible(
                mode
                in {
                    CuteCanvas.CONTROL_MODE_VECTOR_SHAPE,
                    CuteCanvas.CONTROL_MODE_VECTOR_PATH,
                    CuteCanvas.CONTROL_MODE_VECTOR_NODE,
                    CuteCanvas.CONTROL_MODE_VECTOR_TEXT,
                }
            )
            creating = mode in {
                CuteCanvas.CONTROL_MODE_VECTOR_SHAPE,
                CuteCanvas.CONTROL_MODE_VECTOR_PATH,
            }
            for widget in (
                self._shape_combo,
                self._fill_button,
                self._stroke_button,
                self._width,
            ):
                widget.setVisible(creating)
            text_mode = mode == CuteCanvas.CONTROL_MODE_VECTOR_TEXT
            for widget in (self._font, self._font_size, self._alignment):
                widget.setVisible(text_mode)
            for action in (
                self._bold,
                self._italic,
                self._commit_text,
                self._cancel_text,
                self._text_to_paths,
            ):
                action.setVisible(text_mode)

    def refresh(self, *_args: object) -> None:
        """Refresh controls from public vector options and active scene state."""
        scene = self._qpane.currentScene()
        self.add_layer_action.setEnabled(scene is not None)
        target = self._vector_target()
        self.to_selection_action.setEnabled(target is not None)
        selected = self._selected_layer()
        direct_vector = bool(
            selected is not None and selected[2].source_kind == "vector"
        )
        self.rasterize_action.setEnabled(direct_vector)
        self.mask_below_action.setEnabled(
            direct_vector and selected is not None and selected[3] > 0
        )
        self.remove_mask_action.setEnabled(
            bool(
                selected is not None
                and self._qpane.vectorMaskState(selected[0], selected[1]) is not None
            )
        )
        shape = self._qpane.vectorToolShape()
        style = self._qpane.vectorToolStyle()
        if hasattr(self, "_shape_combo"):
            self._shape_combo.blockSignals(True)
            self._shape_combo.setCurrentIndex(self._shape_combo.findData(shape))
            self._shape_combo.blockSignals(False)
            self._width.blockSignals(True)
            self._width.setValue(style.stroke_width)
            self._width.blockSignals(False)
            self._apply_color_swatch(self._fill_button, style.fill)
            self._apply_color_swatch(self._stroke_button, style.stroke)
            text_style = self._qpane.vectorTextStyle()
            paragraph = self._qpane.vectorParagraphStyle()
            self._font.blockSignals(True)
            self._font.setCurrentFont(QFont(text_style.families[0]))
            self._font.blockSignals(False)
            self._font_size.blockSignals(True)
            self._font_size.setValue(text_style.font_size)
            self._font_size.blockSignals(False)
            self._bold.setChecked(text_style.weight >= 600)
            self._italic.setChecked(text_style.italic)
            self._alignment.blockSignals(True)
            self._alignment.setCurrentIndex(
                self._alignment.findData(paragraph.alignment)
            )
            self._alignment.blockSignals(False)
            active_text = self._qpane.vectorTextEditState() is not None
            self._commit_text.setEnabled(active_text)
            self._cancel_text.setEnabled(active_text)
            self._text_to_paths.setEnabled(self._selected_text_object() is not None)

    def _add_layer(self) -> None:
        """Create, select, and enter shape mode for an authoring layer."""
        scene = self._qpane.currentScene()
        layer_id = self._qpane.createVectorLayer(label="Vector Artwork")
        if scene is None or layer_id is None:
            self._show_status("Load an image before adding vector artwork.")
            return
        self._qpane.setSelectedLayer(scene.scene_id, layer_id)
        self._set_mode(CuteCanvas.CONTROL_MODE_VECTOR_SHAPE)
        self._show_status("Added a vector layer. Drag to create a shape.")

    def _set_shape(self, _index: int) -> None:
        """Apply the selected parametric kind through the public facade."""
        value = self._shape_combo.currentData()
        if isinstance(value, VectorShapeKind):
            self._qpane.setVectorToolShape(value)

    def _choose_fill(self) -> None:
        """Choose a detached fill color for future vector objects."""
        style = self._qpane.vectorToolStyle()
        initial = style.fill or QColor(255, 255, 255, 255)
        color = QColorDialog.getColor(
            initial,
            self._fill_button,
            "Vector Fill",
            QColorDialog.ColorDialogOption.ShowAlphaChannel,
        )
        if color.isValid():
            self._qpane.setVectorToolStyle(replace(style, fill=color))

    def _choose_stroke(self) -> None:
        """Choose a detached stroke color for future vector objects."""
        style = self._qpane.vectorToolStyle()
        initial = style.stroke or QColor(255, 255, 255, 255)
        color = QColorDialog.getColor(
            initial,
            self._stroke_button,
            "Vector Stroke",
            QColorDialog.ColorDialogOption.ShowAlphaChannel,
        )
        if color.isValid():
            self._qpane.setVectorToolStyle(replace(style, stroke=color))

    def _set_width(self, width: float) -> None:
        """Replace only the stroke-width field in the creation style."""
        self._qpane.setVectorToolStyle(
            replace(self._qpane.vectorToolStyle(), stroke_width=width)
        )

    def _set_text_family(self, font) -> None:
        """Apply the chosen family to creation or active semantic text."""
        style = self._qpane.vectorTextStyle()
        self._qpane.setVectorTextStyle(replace(style, families=(font.family(),)))

    def _set_text_size(self, size: float) -> None:
        """Apply the chosen semantic text size."""
        self._qpane.setVectorTextStyle(
            replace(self._qpane.vectorTextStyle(), font_size=size)
        )

    def _set_text_bold(self, enabled: bool) -> None:
        """Toggle a conventional semibold text weight."""
        self._qpane.setVectorTextStyle(
            replace(self._qpane.vectorTextStyle(), weight=700 if enabled else 400)
        )

    def _set_text_italic(self, enabled: bool) -> None:
        """Toggle italic semantic text styling."""
        self._qpane.setVectorTextStyle(
            replace(self._qpane.vectorTextStyle(), italic=enabled)
        )

    def _set_text_alignment(self, _index: int) -> None:
        """Apply paragraph alignment without rasterizing the text."""
        alignment = self._alignment.currentData()
        if isinstance(alignment, VectorTextAlignment):
            self._qpane.setVectorParagraphStyle(
                replace(self._qpane.vectorParagraphStyle(), alignment=alignment)
            )

    def _selected_text_object(self) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID] | None:
        """Return the one selected semantic text object, when available."""
        target = self._vector_target()
        selection = self._qpane.vectorSelectionState()
        if target is None or selection is None or len(selection.object_ids) != 1:
            return None
        state = self._qpane.vectorDocumentState(*target)
        object_id = selection.object_ids[0]
        item = (
            None
            if state is None
            else next(
                (
                    candidate
                    for candidate in state.objects
                    if candidate.object_id == object_id
                ),
                None,
            )
        )
        return None if item is None or item.text is None else (*target, object_id)

    def _convert_text_to_paths(self) -> None:
        """Explicitly replace selected text with editable glyph outlines."""
        target = self._selected_text_object()
        if target is None:
            return
        self._qpane.commitVectorTextEdit()
        request_id = self._qpane.convertVectorTextToPaths(*target)
        if request_id is not None:
            self._show_status("Converting text to editable vector paths...")

    def _vector_target(self) -> tuple[uuid.UUID, uuid.UUID] | None:
        """Return the selected public vector layer without private inspection."""
        selected = self._selected_layer()
        if selected is None:
            return None
        return (
            None
            if self._qpane.vectorDocumentState(selected[0], selected[1]) is None
            else (selected[0], selected[1])
        )

    def _selected_layer(self) -> tuple[uuid.UUID, uuid.UUID, object, int] | None:
        """Return selected public layer state and its bottom-to-top index."""
        scene = self._qpane.currentScene()
        selected = self._qpane.selectedLayer()
        if scene is None or selected is None:
            return None
        for index, layer in enumerate(scene.layers):
            if layer.layer_id == selected.layer_id:
                return scene.scene_id, layer.layer_id, layer, index
        return None

    def _convert_to_selection(self) -> None:
        """Convert selected objects, or the whole document, to pixel coverage."""
        target = self._vector_target()
        if target is None:
            return
        request_id = self._qpane.convertVectorToPixelSelection(*target)
        if request_id is not None:
            self._show_status("Converting vector artwork to a pixel selection...")

    def _rasterize(self) -> None:
        """Explicitly replace the selected vector instance with editable pixels."""
        target = self._vector_target()
        if target is None:
            return
        request_id = self._qpane.rasterizeVectorLayer(*target)
        if request_id is not None:
            self._show_status("Rasterizing vector artwork...")

    def _mask_layer_below(self) -> None:
        """Promote the selected vector layer into the adjacent lower layer's mask."""
        selected = self._selected_layer()
        scene = self._qpane.currentScene()
        if selected is None or scene is None or selected[3] <= 0:
            return
        target = scene.layers[selected[3] - 1]
        selection = self._qpane.vectorSelectionState()
        object_ids = (
            None
            if selection is None or selection.layer_id != selected[1]
            else selection.object_ids
        )
        if self._qpane.setVectorMask(
            selected[0],
            selected[1],
            target.layer_id,
            object_ids,
        ):
            self._show_status("Attached an editable vector mask to the layer below.")

    def _remove_mask(self) -> None:
        """Remove the selected layer's vector mask through normal history."""
        selected = self._selected_layer()
        if selected is not None and self._qpane.clearVectorMask(
            selected[0],
            selected[1],
        ):
            self._show_status("Removed the vector mask. Undo restores it.")

    def _handle_request_completed(
        self,
        _request_id: object,
        _scene_id: object,
        _layer_id: object,
        kind: str,
        succeeded: bool,
        message: str,
    ) -> None:
        """Present one concise terminal conversion outcome."""
        label = {
            "pixel-selection": "Pixel selection",
            "editable-raster": "Rasterization",
            "text-paths": "Text-to-path conversion",
        }.get(kind, "Vector conversion")
        if succeeded:
            self._show_status(f"{label} complete.")
        else:
            self._show_status(f"{label} failed: {message}")
        self.refresh()

    @staticmethod
    def _apply_color_swatch(button: QToolButton, color: QColor | None) -> None:
        """Show one restrained color swatch without custom icon assets."""
        if color is None:
            button.setStyleSheet("")
            return
        button.setStyleSheet(
            "QToolButton { border-bottom: 3px solid " + color.name() + "; }"
        )
