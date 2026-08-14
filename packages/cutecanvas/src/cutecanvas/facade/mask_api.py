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

"""Host-facing mask-layer creation, activation, and editing operations."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage

from cutecanvas.masks.export import MaskExportSnapshot, MaskImageExportService
from cutecanvas.masks.workflow import MaskInfo
from cutecanvas.types import LayerEdgeOperation

if TYPE_CHECKING:
    from cutecanvas.composition.scene_adapter import CompositionSceneAdapter
    from cutecanvas.masks.mask_service import MaskService
    from cutecanvas.masks.mask_undo import MaskUndoState


class MaskApiMixin:
    """Expose mask operations without owning mask state or rendering."""

    def activeMaskID(self) -> uuid.UUID | None:
        """Return the active mask resource identity."""
        return self._masks_controller.getActiveMaskID()

    def maskIDsForComposition(
        self,
        composition_id: uuid.UUID | None = None,
    ) -> list[uuid.UUID]:
        """Return mask resource identities for one composition."""
        return self._masks_controller.maskIDsForComposition(composition_id)

    def listMasksForComposition(
        self,
        composition_id: uuid.UUID | None = None,
    ) -> tuple[MaskInfo, ...]:
        """Return mask metadata for one composition."""
        return self._masks_controller.listMasksForComposition(composition_id)

    def getActiveMaskImage(self) -> QImage | None:
        """Return the active mask clipped to the document canvas."""
        return self._masks_controller.get_active_mask_image()

    def beginMaskEdgePreview(self, mask_id: uuid.UUID) -> uuid.UUID | None:
        """Begin a nonmodal whole-mask edge preview through its layer adapter."""
        scene_id, layer_id = self._mask_layer_address(mask_id)
        if scene_id is None or layer_id is None:
            return None
        return self.beginLayerEdgePreview(scene_id, layer_id)

    def expandMaskEdges(self, mask_id: uuid.UUID, pixels: int) -> uuid.UUID | None:
        """Expand complete mask coverage as one asynchronous history edit."""
        return self._request_mask_edge(mask_id, LayerEdgeOperation.EXPAND, pixels)

    def contractMaskEdges(self, mask_id: uuid.UUID, pixels: int) -> uuid.UUID | None:
        """Contract complete mask coverage as one asynchronous history edit."""
        return self._request_mask_edge(mask_id, LayerEdgeOperation.CONTRACT, pixels)

    def featherMaskEdges(self, mask_id: uuid.UUID, radius: float) -> uuid.UUID | None:
        """Feather complete mask coverage as one asynchronous history edit."""
        return self._request_mask_edge(mask_id, LayerEdgeOperation.FEATHER, radius)

    def _request_mask_edge(
        self,
        mask_id: uuid.UUID,
        operation: LayerEdgeOperation,
        radius: float,
    ) -> uuid.UUID | None:
        """Resolve one mask instance and submit its generic layer operation."""
        scene_id, layer_id = self._mask_layer_address(mask_id)
        if scene_id is None or layer_id is None:
            return None
        return self._request_layer_edge_operation(
            scene_id,
            layer_id,
            operation,
            radius,
        )

    def _mask_layer_address(
        self,
        mask_id: uuid.UUID,
    ) -> tuple[uuid.UUID | None, uuid.UUID | None]:
        """Return the current composition instance address for one mask."""
        if not isinstance(mask_id, uuid.UUID):
            raise TypeError("mask_id must be a UUID")
        info = self._masks_controller.maskInfo(mask_id)
        return (None, None) if info is None else (info.scene_id, info.layer_id)

    def exportMaskImage(
        self,
        mask_id: uuid.UUID,
        *,
        composition_id: uuid.UUID | None = None,
    ) -> QImage | None:
        """Export one mask without changing the active document or active mask.

        Args:
            mask_id: Stable identity of the mask resource to export.
            composition_id: Optional composition containing that mask. Supply it
                when the mask is shared by multiple non-active compositions.

        Returns:
            A detached grayscale image clipped to the selected composition, or
            ``None`` when the addressed mask instance cannot be resolved.
        """
        service = self._masks_controller.mask_service()
        adapter = self._composition_scene_adapter
        if service is None or adapter is None:
            return None
        return self._mask_export_service(service, adapter).export(
            mask_id,
            composition_id=composition_id,
        )

    def captureMaskExport(
        self,
        mask_id: uuid.UUID,
        *,
        composition_id: uuid.UUID | None = None,
    ) -> MaskExportSnapshot | None:
        """Capture one exact mask revision and its canvas-bounded pixels."""
        service = self._masks_controller.mask_service()
        adapter = self._composition_scene_adapter
        if service is None or adapter is None:
            return None
        return self._mask_export_service(service, adapter).capture(
            mask_id,
            composition_id=composition_id,
        )

    def _mask_export_service(
        self,
        service: MaskService,
        adapter: CompositionSceneAdapter,
    ) -> MaskImageExportService:
        """Build the stateless mask export boundary from authoritative owners."""
        resources = self.document().resources.resources
        return MaskImageExportService(
            assets=service.assets,
            composition_ids_for_mask=service.composition_ids_for_mask,
            current_composition_id=self.currentCompositionID,
            scene_for_composition=adapter.scene_for,
            resource_revision=lambda resource_id: (
                None
                if (record := resources.get(resource_id)) is None
                else record.revision
            ),
        )

    def getMaskUndoState(self, mask_id: uuid.UUID) -> MaskUndoState | None:
        """Return undo and redo depth for one mask resource."""
        return self._masks_controller.get_mask_undo_state(mask_id)

    def maskFeatureAvailable(self) -> bool:
        """Return whether mask editing is available."""
        return self._masks_controller.mask_feature_available()

    def samFeatureAvailable(self) -> bool:
        """Return whether optional assisted selection is available."""
        return self._masks_controller.sam_feature_available()

    def samCheckpointReady(self) -> bool:
        """Return whether the configured model checkpoint is ready."""
        manager = self._sam_manager
        return False if manager is None else manager.checkpointReady()

    def samCheckpointPath(self) -> Path | None:
        """Return the configured model checkpoint path."""
        manager = self._sam_manager
        return None if manager is None else manager.checkpointPath()

    def refreshSamFeature(self) -> tuple[bool, str]:
        """Reinstall optional assisted-selection support."""
        if "sam" not in self.installedFeatures:
            return False, "SAM tools disabled in this mode."
        try:
            from cutecanvas.masks.sam_feature import install_sam_feature
            from qpane.sdk.features import FeatureInstallError

            self._masks_controller.detachSamManager()
            install_sam_feature(self)
        except FeatureInstallError as exc:
            hint = f" {exc.hint}" if exc.hint else ""
            return False, f"SAM refresh failed: {exc}.{hint}".strip()
        except Exception as exc:  # noqa: BLE001 - optional backend boundary
            return False, f"SAM refresh failed: {exc}."
        return True, "SAM refreshed."

    def createBlankMask(
        self,
        size: QSize,
        *,
        undoable: bool = True,
    ) -> uuid.UUID | None:
        """Create an empty mask with optional document-admission history."""
        mask_id = self._masks_controller.create_blank_mask(
            size,
            undoable=undoable,
        )
        if mask_id is not None:
            self._emit_composition_changed()
            self._emit_scene_changed()
        return mask_id

    def loadMaskFromFile(
        self,
        path: str,
        *,
        undoable: bool = True,
    ) -> uuid.UUID | None:
        """Load a mask with optional document-admission history."""
        mask_id = self._masks_controller.load_mask_from_file(
            path,
            undoable=undoable,
        )
        if mask_id is not None:
            self._emit_composition_changed()
            self._emit_scene_changed()
        return mask_id

    def replaceMaskFromFile(self, mask_id: uuid.UUID, path: str) -> bool:
        """Replace one mask's pixels from a file while retaining its identity."""
        service = self._masks_controller.mask_service()
        return False if service is None else service.updateMaskFromPath(mask_id, path)

    def replaceMaskImage(self, mask_id: uuid.UUID, image: QImage) -> bool:
        """Replace one mask's pixels from an image while retaining its identity."""
        service = self._masks_controller.mask_service()
        return False if service is None else service.updateMaskFromImage(mask_id, image)

    def removeMaskFromComposition(
        self,
        composition_id: uuid.UUID,
        mask_id: uuid.UUID,
    ) -> bool:
        """Remove one mask instance from a composition."""
        self._cancel_floating_pixels_for_context_change()
        removed = self._masks_controller.remove_mask_from_composition(
            composition_id,
            mask_id,
        )
        if removed:
            self._emit_composition_changed()
            self._emit_scene_changed()
        return removed

    def setActiveMaskID(self, mask_id: uuid.UUID | None) -> bool:
        """Set the active mask and its generalized editing destination."""
        self._cancel_floating_pixels_for_context_change()
        changed = self._masks_controller.set_active_mask_id(mask_id)
        if changed:
            self._synchronize_active_mask_layer_selection()
            self._emit_scene_changed()
        return changed

    def setMaskProperties(
        self,
        mask_id: uuid.UUID,
        color: QColor | None = None,
        opacity: float | None = None,
    ) -> bool:
        """Update a mask's presentation properties."""
        changed = self._masks_controller.set_mask_properties(
            mask_id,
            color=color,
            opacity=opacity,
        )
        if changed:
            self._handle_internal_scene_content_changed()
        return changed

    def prefetchMaskOverlays(
        self,
        composition_id: uuid.UUID | None,
        *,
        reason: str = "navigation",
    ) -> bool:
        """Warm mask presentation for a document before it becomes active."""
        return self._masks_controller.prefetch_mask_overlays(
            composition_id,
            reason=reason,
        )

    def cycleMasksForward(self) -> bool:
        """Move the bottom mask to the top of the active mask stack."""
        self._cancel_floating_pixels_for_context_change()
        return self._masks_controller.cycle_masks_forward()

    def cycleMasksBackward(self) -> bool:
        """Move the top mask to the bottom of the active mask stack."""
        self._cancel_floating_pixels_for_context_change()
        return self._masks_controller.cycle_masks_backward()

    def undoMaskEdit(self) -> bool:
        """Undo the last mask or active floating-pixel edit."""
        movement = self._selected_pixel_movement
        if movement is not None and movement.active:
            return self.undoSceneEdit()
        return self._masks_controller.undo_mask_edit()

    def redoMaskEdit(self) -> bool:
        """Redo the last reverted mask edit."""
        movement = self._selected_pixel_movement
        if movement is not None and movement.active:
            return False
        return self._masks_controller.redo_mask_edit()
