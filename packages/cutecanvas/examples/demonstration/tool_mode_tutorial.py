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
"""Teach host-owned tool policy without owning editor or renderer state."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMainWindow, QToolBar

from cutecanvas import CuteCanvas, EditorTransformTarget
from demonstration.brush_controls import BrushControls
from demonstration.clone_stamp_controls import CloneStampControls
from demonstration.coverage_controls import CoverageControls
from demonstration.editor_controls import EditorControls
from demonstration.editor_policy_controls import EditorPolicyControls
from demonstration.extension_tutorial import CUSTOM_TOOL_MODE, LENS_TOOL_MODE
from demonstration.move_controls import MoveControls
from demonstration.vector_controls import VectorControls


class ToolModeTutorialController:
    """Own the demo's tool actions, host policy, and contextual controls."""

    def __init__(
        self,
        canvas: CuteCanvas,
        parent: QMainWindow,
        *,
        masks_available: Callable[[], bool],
        sam_available: Callable[[], bool],
        create_mask: Callable[..., object],
        show_status: Callable[[str], None],
        document_refresh: Callable[[], None],
        extension_actions: Callable[[], tuple[QAction | None, QAction | None]],
    ) -> None:
        """Create controls while keeping mutable document state in CuteCanvas."""
        self._canvas = canvas
        self._transform_target = EditorTransformTarget.LAYER_CONTENT
        self._parent = parent
        self._masks_available = masks_available
        self._sam_available = sam_available
        self._create_mask = create_mask
        self._show_status = show_status
        self._document_refresh = document_refresh
        self._extension_actions = extension_actions
        self._tool_state: tuple[bool, bool] | None = None
        self._create_mode_actions()
        self.editor_controls = EditorControls(
            canvas,
            set_mode=self.set_mode,
            show_status=show_status,
            parent=parent,
        )
        self.editor_policy_controls = EditorPolicyControls(
            canvas,
            show_status=show_status,
            parent=parent,
        )
        self.vector_controls = VectorControls(
            canvas,
            set_mode=self.set_mode,
            show_status=show_status,
            parent=parent,
        )
        self.coverage_controls: CoverageControls | None = None
        self.brush_controls: BrushControls | None = None
        self.clone_stamp_controls: CloneStampControls | None = None
        self.move_controls: MoveControls | None = None

    def build_context_toolbars(self) -> None:
        """Create the persistent editing context toolbars once."""
        if self.move_controls is None:
            move_toolbar = QToolBar("Move Controls", self._parent)
            self._parent.addToolBar(move_toolbar)
            self.move_controls = MoveControls(
                self._canvas,
                move_toolbar,
                parent=self._parent,
            )
        if self.coverage_controls is None:
            coverage_toolbar = QToolBar("Coverage Controls", self._parent)
            self._parent.addToolBar(coverage_toolbar)
            self.coverage_controls = CoverageControls(
                self._canvas,
                coverage_toolbar,
                fill_selection=self.editor_controls.fill_selection_action,
                rasterize_mask=self.editor_controls.rasterize_mask_action,
                parent=self._parent,
            )
        if self.brush_controls is None:
            brush_toolbar = QToolBar("Brush Controls", self._parent)
            self._parent.addToolBar(brush_toolbar)
            self.brush_controls = BrushControls(
                self._canvas,
                brush_toolbar,
                parent=self._parent,
            )
            self.clone_stamp_controls = CloneStampControls(
                self._canvas,
                brush_toolbar,
                parent=self._parent,
            )
        vector_toolbar = getattr(self, "_vector_toolbar", None)
        if vector_toolbar is None:
            vector_toolbar = QToolBar("Vector Controls", self._parent)
            self._parent.addToolBar(vector_toolbar)
            self.vector_controls.build_context_toolbar(vector_toolbar)
            self._vector_toolbar = vector_toolbar

    def set_mode(self, mode: str) -> None:
        """Select a mode after resolving and validating its edit destination."""
        self.editor_controls.layer_policy.reconcile()
        activation_note: str | None = None
        if mode in {
            CuteCanvas.CONTROL_MODE_DRAW_BRUSH,
            CuteCanvas.CONTROL_MODE_ERASER,
        }:
            target = self._canvas.paintTargetState()
            scene = self._canvas.currentScene()
            selected_layer = self._selected_layer()
            if selected_layer is not None and selected_layer.source_kind in {
                "coverage",
                "raster",
            }:
                assert scene is not None
                self._canvas.setPaintTarget(scene.scene_id, selected_layer.layer_id)
                target = self._canvas.paintTargetState()
            if selected_layer is None and target is None and self._masks_available():
                if not self._ensure_active_mask():
                    return
                self.editor_controls.layer_policy.select_active_mask_layer()
                target = self._canvas.paintTargetState()
            if selected_layer is None and target is None:
                self._show_status("Add or select a paint-capable layer first.")
                return
            if selected_layer is not None and target is None:
                activation_note = (
                    "Brush selected. Drawing creates and selects a paint layer "
                    "above this layer."
                )
        if mode == CuteCanvas.CONTROL_MODE_CLONE_STAMP:
            scene = self._canvas.currentScene()
            selected_layer = self._selected_layer()
            if scene is None or selected_layer is None:
                activation_note = (
                    "Clone Stamp selected. Select a layer and Alt-click a source."
                )
            elif not (
                selected_layer.source_kind == "raster"
                and self._canvas.setPaintTarget(
                    scene.scene_id,
                    selected_layer.layer_id,
                )
            ):
                activation_note = (
                    "Clone Stamp selected. Alt-click a source; painting creates "
                    "and selects a raster layer above this layer."
                )
        if mode == CuteCanvas.CONTROL_MODE_SMART_SELECT and not self._sam_available():
            self._show_status("Enable SAM tools to use Smart Select.")
            return
        if mode == CuteCanvas.CONTROL_MODE_SMART_MASK:
            if not (self._masks_available() and self._sam_available()):
                self._show_status("Enable mask and SAM tools to use Smart Mask.")
                return
            if not self._ensure_active_mask():
                return
            self.editor_controls.layer_policy.select_active_mask_layer()
        if mode in {
            CuteCanvas.CONTROL_MODE_VECTOR_SHAPE,
            CuteCanvas.CONTROL_MODE_VECTOR_PATH,
            CuteCanvas.CONTROL_MODE_VECTOR_NODE,
            CuteCanvas.CONTROL_MODE_VECTOR_TEXT,
        }:
            scene = self._canvas.currentScene()
            selected_layer = self._selected_layer()
            if (
                scene is None
                or selected_layer is None
                or self._canvas.vectorDocumentState(
                    scene.scene_id,
                    selected_layer.layer_id,
                )
                is None
            ):
                self._show_status("Add or select a vector layer first.")
                return
        self._canvas.setControlMode(mode)
        self._show_status(activation_note or f"Mode: {self.describe_mode(mode)}")
        self._document_refresh()

    def cycle_mode(self) -> None:
        """Advance through modes that are valid for the current host state."""
        has_document = self._canvas.currentCompositionID() is not None
        preferred = [
            CuteCanvas.CONTROL_MODE_CURSOR,
            CuteCanvas.CONTROL_MODE_PANZOOM,
            CuteCanvas.CONTROL_MODE_MOVE,
            CuteCanvas.CONTROL_MODE_TRANSFORM,
            CuteCanvas.CONTROL_MODE_SHARED_EDGE_RESIZE,
            CuteCanvas.CONTROL_MODE_DRAW_BRUSH,
            CuteCanvas.CONTROL_MODE_ERASER,
            CuteCanvas.CONTROL_MODE_CLONE_STAMP,
        ]
        if self._sam_available():
            preferred.append(CuteCanvas.CONTROL_MODE_SMART_SELECT)
            if self._masks_available():
                preferred.append(CuteCanvas.CONTROL_MODE_SMART_MASK)
        seen = set(preferred)
        preferred.extend(
            mode for mode in self._canvas.availableControlModes() if mode not in seen
        )

        def mode_allowed(mode: str) -> bool:
            """Return whether one mode is meaningful for the visible content."""
            if mode == CuteCanvas.CONTROL_MODE_PANZOOM:
                return has_document
            if mode == CuteCanvas.CONTROL_MODE_SMART_SELECT:
                return self._sam_available() and has_document
            if mode == CuteCanvas.CONTROL_MODE_SMART_MASK:
                return (
                    self._masks_available() and self._sam_available() and has_document
                )
            return has_document or mode == CuteCanvas.CONTROL_MODE_CURSOR

        ordered = [mode for mode in preferred if mode_allowed(mode)]
        if not ordered:
            return
        current = self._canvas.getControlMode()
        if current not in ordered:
            self.set_mode(ordered[0])
        elif len(ordered) > 1:
            self.set_mode(ordered[(ordered.index(current) + 1) % len(ordered)])

    def apply_document_focus(self, kind: str) -> None:
        """Choose a useful tool when the layer tree changes target kind."""
        current = self._canvas.getControlMode()
        if kind == "coverage":
            if current not in {
                CuteCanvas.CONTROL_MODE_MOVE,
                CuteCanvas.CONTROL_MODE_TRANSFORM,
                CuteCanvas.CONTROL_MODE_SHARED_EDGE_RESIZE,
                CuteCanvas.CONTROL_MODE_DRAW_BRUSH,
                CuteCanvas.CONTROL_MODE_ERASER,
                CuteCanvas.CONTROL_MODE_CLONE_STAMP,
                CuteCanvas.CONTROL_MODE_SMART_MASK,
            }:
                self.set_mode(CuteCanvas.CONTROL_MODE_DRAW_BRUSH)
        elif kind in {"raster", "imported-raster", "linked-raster"} and current not in {
            CuteCanvas.CONTROL_MODE_CURSOR,
            CuteCanvas.CONTROL_MODE_PANZOOM,
            CuteCanvas.CONTROL_MODE_MOVE,
            CuteCanvas.CONTROL_MODE_TRANSFORM,
            CuteCanvas.CONTROL_MODE_SHARED_EDGE_RESIZE,
            CuteCanvas.CONTROL_MODE_DRAW_BRUSH,
            CuteCanvas.CONTROL_MODE_ERASER,
            CuteCanvas.CONTROL_MODE_CLONE_STAMP,
        }:
            self.set_mode(CuteCanvas.CONTROL_MODE_PANZOOM)

    def sync_mode(self, mode: str) -> None:
        """Mirror the authoritative mode into every related control."""
        self.mode_cursor_action.setChecked(mode == CuteCanvas.CONTROL_MODE_CURSOR)
        self.mode_pan_action.setChecked(mode == CuteCanvas.CONTROL_MODE_PANZOOM)
        self.mode_move_action.setChecked(mode == CuteCanvas.CONTROL_MODE_MOVE)
        self.mode_shared_edge_action.setChecked(
            mode == CuteCanvas.CONTROL_MODE_SHARED_EDGE_RESIZE
        )
        transforming = mode == CuteCanvas.CONTROL_MODE_TRANSFORM
        self.mode_transform_action.setChecked(
            transforming
            and self._transform_target is EditorTransformTarget.LAYER_CONTENT
        )
        self.mode_transform_selection_action.setChecked(
            transforming
            and self._transform_target is EditorTransformTarget.SELECTION_CONTENT
        )
        self.mode_brush_action.setChecked(mode == CuteCanvas.CONTROL_MODE_DRAW_BRUSH)
        self.mode_eraser_action.setChecked(mode == CuteCanvas.CONTROL_MODE_ERASER)
        self.mode_clone_stamp_action.setChecked(
            mode == CuteCanvas.CONTROL_MODE_CLONE_STAMP
        )
        if self.mode_smart_action is not None:
            self.mode_smart_action.setChecked(
                mode == CuteCanvas.CONTROL_MODE_SMART_SELECT
            )
        if self.mode_smart_mask_action is not None:
            self.mode_smart_mask_action.setChecked(
                mode == CuteCanvas.CONTROL_MODE_SMART_MASK
            )
        custom_action, lens_action = self._extension_actions()
        if custom_action is not None:
            custom_action.setChecked(mode == CUSTOM_TOOL_MODE)
        if lens_action is not None:
            lens_action.setChecked(mode == LENS_TOOL_MODE)
        self.editor_controls.sync_mode(mode)
        if self.move_controls is not None:
            self.move_controls.sync_mode(mode)
        if self.coverage_controls is not None:
            self.coverage_controls.sync_mode(mode)
        if self.brush_controls is not None:
            self.brush_controls.sync_mode(mode)
        if self.clone_stamp_controls is not None:
            self.clone_stamp_controls.sync_mode(mode)
        self.vector_controls.sync_mode(mode)

    def refresh_availability(self) -> None:
        """Apply host feature and composition policy to all tool controls."""
        has_document = self._canvas.currentCompositionID() is not None
        panzoom = has_document
        sam_available = self._sam_available()

        def enable(action: QAction | None, enabled: bool) -> None:
            """Enable one action and clear an invalid checked state."""
            if action is None:
                return
            action.setEnabled(enabled)
            if not enabled:
                self._set_checked(action, False)

        enable(self.mode_pan_action, panzoom)
        self.mode_cursor_action.setEnabled(True)
        enable(self.mode_move_action, has_document)
        enable(self.mode_shared_edge_action, has_document)
        enable(self.mode_transform_action, has_document)
        enable(
            self.mode_transform_selection_action,
            has_document
            and self._canvas.editorTransformState(
                EditorTransformTarget.SELECTION_CONTENT
            ).allowed,
        )
        enable(self.mode_brush_action, has_document)
        enable(self.mode_eraser_action, has_document)
        enable(self.mode_clone_stamp_action, has_document)
        enable(self.mode_smart_action, sam_available and has_document)
        enable(
            self.mode_smart_mask_action,
            sam_available and self._masks_available() and has_document,
        )
        custom_action, lens_action = self._extension_actions()
        enable(custom_action, custom_action is not None and has_document)
        enable(lens_action, lens_action is not None and has_document)
        allowed = {CuteCanvas.CONTROL_MODE_CURSOR}
        if has_document:
            allowed.update(
                {
                    CuteCanvas.CONTROL_MODE_MOVE,
                    CuteCanvas.CONTROL_MODE_TRANSFORM,
                    CuteCanvas.CONTROL_MODE_SHARED_EDGE_RESIZE,
                    CuteCanvas.CONTROL_MODE_DRAW_BRUSH,
                    CuteCanvas.CONTROL_MODE_ERASER,
                    CuteCanvas.CONTROL_MODE_CLONE_STAMP,
                    CuteCanvas.CONTROL_MODE_VECTOR_SHAPE,
                    CuteCanvas.CONTROL_MODE_VECTOR_PATH,
                    CuteCanvas.CONTROL_MODE_VECTOR_NODE,
                    CuteCanvas.CONTROL_MODE_VECTOR_TEXT,
                }
            )
        if panzoom:
            allowed.add(CuteCanvas.CONTROL_MODE_PANZOOM)
        if sam_available and has_document:
            allowed.add(CuteCanvas.CONTROL_MODE_SMART_SELECT)
            if self._masks_available():
                allowed.add(CuteCanvas.CONTROL_MODE_SMART_MASK)
        if custom_action is not None and has_document:
            allowed.add(CUSTOM_TOOL_MODE)
        if lens_action is not None and has_document:
            allowed.add(LENS_TOOL_MODE)
        self.cycle_mode_action.setEnabled(len(allowed) > 1)
        current = self._canvas.getControlMode()
        if current not in allowed:
            current = (
                CuteCanvas.CONTROL_MODE_PANZOOM
                if panzoom
                else CuteCanvas.CONTROL_MODE_CURSOR
            )
            self.set_mode(current)
        self.sync_mode(current)
        previous = self._tool_state
        self._tool_state = (not has_document, panzoom)
        if not has_document and previous != self._tool_state:
            self._show_status("Open a document to enable canvas tools.")
        elif previous and previous[0] and has_document:
            self._show_status("Document selected; canvas tools are available.")

    def mode_actions(self) -> list[QAction | None]:
        """Return ordered mode actions for the compact tools toolbar."""
        custom_action, lens_action = self._extension_actions()
        return [
            self.mode_cursor_action,
            self.mode_pan_action,
            self.mode_move_action,
            self.mode_shared_edge_action,
            self.mode_transform_action,
            self.mode_transform_selection_action,
            self.mode_brush_action,
            self.mode_eraser_action,
            self.mode_clone_stamp_action,
            self.editor_controls.paint_bucket_action,
            self.mode_smart_action,
            self.mode_smart_mask_action,
            custom_action,
            lens_action,
        ]

    def _create_mode_actions(self) -> None:
        """Create the mode actions demonstrated by the host shell."""
        self.mode_pan_action = QAction("Pan/Zoom", self._parent, checkable=True)
        self.mode_cursor_action = QAction("Cursor", self._parent, checkable=True)
        self.mode_move_action = QAction("Move", self._parent, checkable=True)
        self.mode_shared_edge_action = QAction(
            "Shared Edge Resize", self._parent, checkable=True
        )
        self.mode_shared_edge_action.setStatusTip(
            "Resize every layer in a coincident-edge group as one atomic edit."
        )
        self.mode_move_action.setStatusTip(
            "Drag selected content without disturbing pixels beneath transparent "
            "holes, or move a layer when no pixel selection is active."
        )
        self.mode_transform_action = QAction(
            "Transform Layer Content", self._parent, checkable=True
        )
        self.mode_transform_action.setShortcut(QKeySequence("Ctrl+T"))
        self.mode_transform_action.setStatusTip(
            "Move or resize the selected layer's tight content bounds with snapping; "
            "hold Ctrl to suppress snaps."
        )
        self.mode_transform_selection_action = QAction(
            "Transform Selection", self._parent, checkable=True
        )
        self.mode_transform_selection_action.setShortcut(QKeySequence("Ctrl+Shift+T"))
        self.mode_transform_selection_action.setStatusTip(
            "Move or resize selected-layer pixels with snapping against the complete "
            "selection bounds."
        )
        self.mode_brush_action = QAction("Brush", self._parent, checkable=True)
        self.mode_eraser_action = QAction("Eraser", self._parent, checkable=True)
        self.mode_clone_stamp_action = QAction(
            "Clone Stamp",
            self._parent,
            checkable=True,
        )
        self.mode_clone_stamp_action.setStatusTip(
            "Alt-click a rendered source, then paint onto the selected layer."
        )
        self.mode_smart_action: QAction | None = None
        self.mode_smart_mask_action: QAction | None = None
        if self._sam_available():
            self.mode_smart_action = QAction(
                "Smart Select", self._parent, checkable=True
            )
            if self._masks_available():
                self.mode_smart_mask_action = QAction(
                    "Smart Mask", self._parent, checkable=True
                )
        bindings = [
            (self.mode_pan_action, CuteCanvas.CONTROL_MODE_PANZOOM),
            (self.mode_cursor_action, CuteCanvas.CONTROL_MODE_CURSOR),
            (self.mode_move_action, CuteCanvas.CONTROL_MODE_MOVE),
            (
                self.mode_shared_edge_action,
                CuteCanvas.CONTROL_MODE_SHARED_EDGE_RESIZE,
            ),
            (self.mode_brush_action, CuteCanvas.CONTROL_MODE_DRAW_BRUSH),
            (self.mode_eraser_action, CuteCanvas.CONTROL_MODE_ERASER),
            (
                self.mode_clone_stamp_action,
                CuteCanvas.CONTROL_MODE_CLONE_STAMP,
            ),
            (self.mode_smart_action, CuteCanvas.CONTROL_MODE_SMART_SELECT),
            (self.mode_smart_mask_action, CuteCanvas.CONTROL_MODE_SMART_MASK),
        ]
        for action, mode in bindings:
            if action is not None:
                action.triggered.connect(
                    lambda _checked=False, value=mode: self.set_mode(value)
                )
        self.mode_transform_action.triggered.connect(
            lambda _checked=False: self._activate_transform(
                EditorTransformTarget.LAYER_CONTENT
            )
        )
        self.mode_transform_selection_action.triggered.connect(
            lambda _checked=False: self._activate_transform(
                EditorTransformTarget.SELECTION_CONTENT
            )
        )
        self.cycle_mode_action = QAction("Cycle Mode", self._parent)
        self.cycle_mode_action.setShortcut(QKeySequence("B"))
        self.cycle_mode_action.triggered.connect(self.cycle_mode)

    def _activate_transform(self, target: EditorTransformTarget) -> None:
        """Demonstrate one public explicit affine target activation."""
        if self._canvas.activateEditorTransform(target):
            self._transform_target = target
            self.sync_mode(CuteCanvas.CONTROL_MODE_TRANSFORM)

    def _selected_layer(self):
        """Resolve the selected layer from the current scene snapshot."""
        scene = self._canvas.currentScene()
        selected = self._canvas.selectedLayer()
        if scene is None or selected is None:
            return None
        return next(
            (layer for layer in scene.layers if layer.layer_id == selected.layer_id),
            None,
        )

    def _ensure_active_mask(self) -> bool:
        """Create an active mask when a mask-dependent mode needs one."""
        if not self._masks_available():
            return False
        scene = self._canvas.currentScene()
        if scene is None or scene.bounds.isEmpty():
            self._show_status("Open a document before using mask tools.")
            return False
        if self._canvas.activeMaskID() is not None:
            return True
        return self._create_mask(announce=True) is not None

    @staticmethod
    def describe_mode(mode: str) -> str:
        """Return a compact display label for a public mode identifier."""
        labels = {
            CuteCanvas.CONTROL_MODE_CURSOR: "Cursor",
            CuteCanvas.CONTROL_MODE_PANZOOM: "Pan / Zoom",
            CuteCanvas.CONTROL_MODE_MOVE: "Move",
            CuteCanvas.CONTROL_MODE_TRANSFORM: "Transform",
            CuteCanvas.CONTROL_MODE_SHARED_EDGE_RESIZE: "Shared Edge Resize",
            CuteCanvas.CONTROL_MODE_DRAW_BRUSH: "Brush",
            CuteCanvas.CONTROL_MODE_ERASER: "Eraser",
            CuteCanvas.CONTROL_MODE_CLONE_STAMP: "Clone Stamp",
            CuteCanvas.CONTROL_MODE_SMART_SELECT: "Smart Select (SAM)",
            CuteCanvas.CONTROL_MODE_SMART_MASK: "Smart Mask (SAM)",
            CuteCanvas.CONTROL_MODE_VECTOR_SHAPE: "Vector Shape",
            CuteCanvas.CONTROL_MODE_VECTOR_PATH: "Vector Path",
            CuteCanvas.CONTROL_MODE_VECTOR_NODE: "Edit Vector Nodes",
            CuteCanvas.CONTROL_MODE_VECTOR_TEXT: "Text",
        }
        return labels.get(mode, mode)

    @staticmethod
    def _set_checked(action: QAction, checked: bool) -> None:
        """Update a checked action without invoking its host command."""
        action.blockSignals(True)
        action.setChecked(checked)
        action.blockSignals(False)
