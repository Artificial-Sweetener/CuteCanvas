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
"""Capability-aware interaction policy for the demonstration host."""

from __future__ import annotations

from cutecanvas import CuteCanvas, LayerPolicy, PaintTargetKind
from PySide6.QtCore import QObject


class DemoLayerPolicyController(QObject):
    """Keep the selected authoring layer editable while catalog images stay frozen."""

    def __init__(self, qpane: CuteCanvas, parent: QObject | None = None) -> None:
        """Observe every public transition that can change layer capabilities."""
        super().__init__(parent)
        self._qpane = qpane
        self._active_mask_id = None
        self._reconciling = False
        qpane.compositionSelectionChanged.connect(self.reconcile)
        qpane.catalogChanged.connect(self.reconcile)
        qpane.catalogSelectionChanged.connect(self.reconcile)
        qpane.currentImageChanged.connect(self.reconcile)
        qpane.selectedLayerChanged.connect(self.reconcile)
        qpane.sceneChanged.connect(self.reconcile)

    def reconcile(self, *_args: object) -> None:
        """Apply the demo policy from current selection and intrinsic capabilities."""
        if self._reconciling:
            return
        self._reconciling = True
        try:
            self._apply_current_policy()
        finally:
            self._reconciling = False

    def select_active_mask_layer(self) -> None:
        """Align selected layer identity with the active mask before editing."""
        active_mask_id = self._qpane.activeMaskID()
        for mask in self._qpane.listMasksForImage():
            if (
                mask.mask_id == active_mask_id
                and mask.scene_id is not None
                and mask.layer_id is not None
            ):
                self._qpane.setSelectedLayer(mask.scene_id, mask.layer_id)
                self.reconcile()
                return

    def _apply_current_policy(self) -> None:
        """Reconcile every current layer through public capability queries."""
        scene = self._qpane.currentScene()
        if scene is None:
            return
        frozen = LayerPolicy(selectable=True)
        selectable = LayerPolicy(selectable=True)
        editable = LayerPolicy(
            selectable=True,
            movable=True,
            pixel_editable=True,
        )
        movable = LayerPolicy(selectable=True, movable=True)
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
        if active_mask_id != self._active_mask_id:
            self._active_mask_id = active_mask_id
            selected_layer_id = active_mask_layer_id
        if selected_layer_id is None:
            selected_layer_id = active_mask_layer_id
        for layer in scene.layers:
            authoring_layer = layer.source_kind != "catalog-image"
            selected_authoring = authoring_layer and layer.layer_id == selected_layer_id
            pixel_editable = bool(
                selected_authoring
                and self._qpane.rasterSurfaceState(
                    scene.scene_id,
                    layer.layer_id,
                )
                is not None
            )
            policy = (
                editable
                if pixel_editable
                else (
                    movable
                    if selected_authoring
                    else selectable if authoring_layer else frozen
                )
            )
            if layer.interaction != policy:
                self._qpane.setLayerInteractionPolicy(
                    scene.scene_id,
                    layer.layer_id,
                    policy,
                )
        if selected_layer_id is None:
            return
        self._qpane.setSelectedLayer(scene.scene_id, selected_layer_id)
        target = self._qpane.paintTargetState()
        if target is not None and target.kind is PaintTargetKind.PIXEL_SELECTION:
            return
        if (
            self._qpane.rasterSurfaceState(scene.scene_id, selected_layer_id)
            is not None
        ):
            self._qpane.setPaintTarget(scene.scene_id, selected_layer_id)
