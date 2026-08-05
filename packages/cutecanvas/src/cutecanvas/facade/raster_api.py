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
"""RasterApi behavior for the CuteCanvas facade."""

from __future__ import annotations

import uuid
from dataclasses import replace

from PySide6.QtCore import (
    QPointF,
    QRect,
    QRectF,
    QSize,
)
from PySide6.QtGui import (
    QColor,
    QImage,
)
from qpane.sdk.scene import RasterBounds

from cutecanvas.composition.public_policy import (
    internal_layer_policy,
)
from cutecanvas.coverage import CoverageCombineMode
from cutecanvas.editor import (
    EditorOperation,
)
from cutecanvas.painting import BrushPreset, BrushTipPreviewRenderer
from cutecanvas.painting.clone_model import (
    CloneStampAlignment,
    CloneStampSampleMode,
    CloneStampState,
    CloneStampTransform,
)
from cutecanvas.resources import ProjectResourceReference
from cutecanvas.types import (
    FloatingPixelMode,
    FloatingPixelSnapshot,
    LayerPolicy,
    PaintTargetSnapshot,
    RasterExtentPolicy,
)


class RasterApiMixin:
    """Group rasterapi facade behavior."""

    def addEditableRasterLayer(
        self,
        image: QImage,
        *,
        placement: QRectF | None = None,
        label: str | None = None,
        interaction: LayerPolicy | None = None,
        extent_policy: RasterExtentPolicy = RasterExtentPolicy.FIXED,
    ) -> uuid.UUID | None:
        """Add a detached editable color raster to the active document.

        Args:
            image: Non-null color raster copied into composition-owned storage.
            placement: Optional scene placement; source dimensions are used by default.
            label: Optional host-facing layer label.
            interaction: Host policy for selection, movement, and pixel editing.
            extent_policy: Fixed, expanding, or unbounded future write behavior.

        Returns:
            The stable layer UUID, or ``None`` when no document is active.
        """
        if not isinstance(image, QImage):
            raise TypeError("image must be a QImage")
        if image.isNull():
            raise ValueError("image must not be null")
        if placement is not None and not isinstance(placement, QRectF):
            raise TypeError("placement must be a QRectF or None")
        if label is not None and not isinstance(label, str):
            raise TypeError("label must be a string or None")
        if interaction is not None and not isinstance(interaction, LayerPolicy):
            raise TypeError("interaction must be LayerPolicy or None")
        if not isinstance(extent_policy, RasterExtentPolicy):
            raise TypeError("extent_policy must be RasterExtentPolicy")
        controller = self._editable_raster_layers
        if controller is None:
            return None
        normalized_interaction = interaction or LayerPolicy(
            selectable=True,
            movable=True,
            pixel_editable=True,
        )
        layer_id = controller.add(
            image,
            placement=placement,
            interaction=internal_layer_policy(normalized_interaction),
            label=label,
            extent_policy=extent_policy,
        )
        if layer_id is not None:
            self._handle_internal_scene_content_changed()
            self._emit_scene_changed()
        return layer_id

    def createPaintLayer(
        self,
        size: QSize | None = None,
        *,
        label: str = "Paint Layer",
        extent_policy: RasterExtentPolicy = RasterExtentPolicy.UNBOUNDED,
    ) -> uuid.UUID | None:
        """Create a transparent editable layer and select it for painting.

        Args:
            size: Initial pixel dimensions, or active scene dimensions when omitted.
            label: Host-facing layer label.
            extent_policy: Fixed or expanding future write behavior.

        Returns:
            The new layer UUID, or ``None`` when no active scene exists.

        Raises:
            TypeError: If arguments use unsupported public types.
            ValueError: If dimensions are not positive or the label is empty.

        Side effects:
            Adds and selects one scene layer and changes the active paint target.
        """
        if size is not None and not isinstance(size, QSize):
            raise TypeError("size must be a QSize or None")
        if not isinstance(label, str):
            raise TypeError("label must be a string")
        if not label.strip():
            raise ValueError("label must not be empty")
        if not isinstance(extent_policy, RasterExtentPolicy):
            raise TypeError("extent_policy must be RasterExtentPolicy")
        scene = self.currentScene()
        if scene is None:
            return None
        initial_size = (
            QSize(size)
            if size is not None
            else QSize(
                max(1, round(scene.bounds.width())),
                max(1, round(scene.bounds.height())),
            )
        )
        if initial_size.width() <= 0 or initial_size.height() <= 0:
            raise ValueError("size dimensions must be positive")
        layer_id = self.editableRasterLayers().add_empty(
            initial_size,
            placement=None,
            interaction=internal_layer_policy(
                LayerPolicy(
                    selectable=True,
                    movable=True,
                    pixel_editable=True,
                )
            ),
            label=label,
            extent_policy=extent_policy,
        )
        if layer_id is not None:
            self._handle_internal_scene_content_changed()
            self._emit_scene_changed()
            self.setSelectedLayer(scene.scene_id, layer_id)
            self.setPaintTarget(scene.scene_id, layer_id)
        return layer_id

    def paintTargetState(self) -> PaintTargetSnapshot | None:
        """Return the detached active generalized paint destination."""
        identity = self.paintingCoordinator().identity
        if identity is None:
            return None
        current_scene = self.currentScene()
        public_scene_id = (
            identity.scene_id if current_scene is None else current_scene.scene_id
        )
        source_kind = None
        if identity.layer_id is not None:
            resolved = self.sceneMutationCoordinator().find_layer(
                lambda layer: (
                    layer.scene_id == identity.scene_id
                    and layer.layer_id == identity.layer_id
                )
            )
            if resolved is None:
                return None
            source_kind = self.compositionService().source_kind(resolved[1].source)
        return PaintTargetSnapshot(
            scene_id=public_scene_id,
            kind=identity.kind,
            layer_id=identity.layer_id,
            source_kind=source_kind,
        )

    def setPaintTarget(self, scene_id: uuid.UUID, layer_id: uuid.UUID) -> bool:
        """Select one pixel-editable active scene layer as the brush target.

        Args:
            scene_id: Public or resolved identifier for the active scene.
            layer_id: Stable identifier of a paint-capable layer.

        Returns:
            True when the target is valid and selected.

        Raises:
            TypeError: If either identifier is not a UUID.
        """
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        resolved_scene_id = self._resolve_public_scene_id(scene_id)
        selection = self.selectedLayer()
        if (
            selection is None
            or selection.scene_id != scene_id
            or selection.layer_id != layer_id
        ):
            self.setSelectedLayer(scene_id, layer_id)
        return self.paintingCoordinator().select_layer(
            resolved_scene_id,
            layer_id,
        )

    def clearPaintTarget(self) -> bool:
        """Cancel unresolved brush work and clear the generalized paint target."""
        return self.paintingCoordinator().clear()

    def brushPreset(self) -> BrushPreset:
        """Return the active immutable brush preset."""
        return self.paintingCoordinator().preset

    def setBrushPreset(self, preset: BrushPreset) -> bool:
        """Replace hardness, opacity, flow, spacing, and brush dynamics.

        Args:
            preset: Valid immutable brush configuration.

        Returns:
            True when the active preset changed.

        Raises:
            TypeError: If ``preset`` is not a ``BrushPreset``.
        """
        if not isinstance(preset, BrushPreset):
            raise TypeError("preset must be BrushPreset")
        if not self.paintingCoordinator().set_preset(preset):
            return False
        self.interaction.brush_size = max(1, round(preset.size))
        self.refreshCursor()
        self.brushPresetChanged.emit(preset)
        return True

    def renderBrushTipPreview(
        self,
        logical_size: QSize,
        *,
        device_pixel_ratio: float = 1.0,
        color: QColor | None = None,
    ) -> QImage:
        """Render the active brush definition for lightweight host controls."""
        return BrushTipPreviewRenderer(
            self.paintingCoordinator().compositor.tips
        ).render(
            self.brushPreset(),
            logical_size,
            device_pixel_ratio=device_pixel_ratio,
            color=color,
        )

    def paintColor(self) -> QColor:
        """Return the detached active color used by color paint targets."""
        return self.paintingCoordinator().color

    def setPaintColor(self, color: QColor) -> bool:
        """Set the detached active color used by color paint targets.

        Args:
            color: Valid Qt color, including alpha.

        Returns:
            True when the paint color changed.

        Raises:
            TypeError: If ``color`` is not a valid ``QColor``.
        """
        if not isinstance(color, QColor) or not color.isValid():
            raise TypeError("color must be a valid QColor")
        if not self.paintingCoordinator().set_color(color):
            return False
        detached = QColor(color)
        self.refreshCursor()
        self.paintColorChanged.emit(detached)
        return True

    def cloneStampState(self) -> CloneStampState:
        """Return source, alignment, and sampling state for Clone Stamp."""
        return self.cloneStampOperation().state

    def setCloneStampSource(self, scene_position: QPointF) -> bool:
        """Set the Clone Stamp source in active-composition scene coordinates."""
        if not isinstance(scene_position, QPointF):
            raise TypeError("scene_position must be QPointF")
        changed = self.cloneStampOperation().set_source(scene_position)
        if changed:
            self.refreshCursor()
        return changed

    def clearCloneStampSource(self) -> bool:
        """Clear the Clone Stamp source and retained aligned offset."""
        changed = self.cloneStampOperation().clear_source()
        if changed:
            self.refreshCursor()
        return changed

    def setCloneStampAlignment(self, alignment: CloneStampAlignment) -> bool:
        """Set whether Clone Stamp preserves its offset between strokes."""
        if not isinstance(alignment, CloneStampAlignment):
            raise TypeError("alignment must be CloneStampAlignment")
        return self.cloneStampOperation().set_alignment(alignment)

    def setCloneStampSampleMode(self, mode: CloneStampSampleMode) -> bool:
        """Choose selected-layer or visible-composite Clone Stamp sampling."""
        if not isinstance(mode, CloneStampSampleMode):
            raise TypeError("mode must be CloneStampSampleMode")
        changed = self.cloneStampOperation().set_sample_mode(mode)
        if changed:
            self.refreshCursor()
        return changed

    def setCloneStampTransform(self, transform: CloneStampTransform) -> bool:
        """Set Clone Stamp rotation, output scale, and reflection."""
        if not isinstance(transform, CloneStampTransform):
            raise TypeError("transform must be CloneStampTransform")
        changed = self.cloneStampOperation().set_transform(transform)
        if changed:
            self.update()
        return changed

    def fillSelection(
        self,
        mode: CoverageCombineMode = CoverageCombineMode.ADD,
    ) -> bool:
        """Fill the active paint target through the composition pixel selection.

        Args:
            mode: Coverage algebra used by coverage destinations such as masks.

        Returns:
            True when one atomic fill edit was committed.
        """
        if not isinstance(mode, CoverageCombineMode):
            raise TypeError("mode must be CoverageCombineMode")
        return self.selectionFillCoordinator().fill(mode)

    def paintBucketOptions(self) -> tuple[int, bool, bool]:
        """Return Paint Bucket tolerance, contiguous, and antialias settings."""
        return self.paintBucketCoordinator().options

    def configurePaintBucket(
        self,
        *,
        tolerance: int | None = None,
        contiguous: bool | None = None,
        antialias: bool | None = None,
    ) -> bool:
        """Configure subsequent asynchronous Paint Bucket requests.

        Args:
            tolerance: Optional channel-distance threshold from zero to 255.
            contiguous: Whether only the seed-connected region is filled.
            antialias: Whether similarity edges retain soft coverage.

        Returns:
            True when at least one option changed.
        """
        if tolerance is not None and not isinstance(tolerance, int):
            raise TypeError("tolerance must be an integer or None")
        if contiguous is not None and not isinstance(contiguous, bool):
            raise TypeError("contiguous must be a bool or None")
        if antialias is not None and not isinstance(antialias, bool):
            raise TypeError("antialias must be a bool or None")
        return self.paintBucketCoordinator().configure(
            tolerance=tolerance,
            contiguous=contiguous,
            antialias=antialias,
        )

    def setBrushSize(self, size: int) -> None:
        """Set the shared brush diameter while preserving all other preset fields.

        Args:
            size: Positive brush diameter in target pixels; values below one clamp.

        Raises:
            TypeError: If ``size`` is not an integer.

        Side effects:
            Refreshes brush feedback and emits ``brushPresetChanged`` on change.
        """
        if not isinstance(size, int):
            raise TypeError("size must be an integer")
        normalized = max(1, size)
        self._masks_controller.set_brush_size(normalized)
        preset = replace(
            self.paintingCoordinator().preset,
            size=float(normalized),
        )
        if self.paintingCoordinator().set_preset(preset):
            self.brushPresetChanged.emit(preset)

    def editableRasterLayerImage(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
    ) -> QImage | None:
        """Return detached pixels for an active editable raster layer."""
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        resolved_scene_id = self._resolve_public_scene_id(scene_id)
        resolved = self.sceneMutationCoordinator().find_layer(
            lambda layer: (
                layer.scene_id == resolved_scene_id and layer.layer_id == layer_id
            )
        )
        if resolved is None or not isinstance(
            resolved[1].source, ProjectResourceReference
        ):
            return None
        assets = self._editable_raster_assets
        asset = None if assets is None else assets.get(resolved[1].source.resource_id)
        return None if asset is None else asset.surface.snapshot_qimage()

    def setRasterExtentPolicy(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        policy: RasterExtentPolicy,
    ) -> bool:
        """Set the write-extent policy for an active raster layer.

        Args:
            scene_id: Public or resolved identifier for the active scene.
            layer_id: Stable identifier of the raster layer to update.
            policy: Fixed or expand-on-write storage behavior.

        Returns:
            True when the source policy changed.

        Raises:
            TypeError: If identifiers or policy use unsupported types.

        Side effects:
            Emits ``sceneChanged`` without changing pixels, bounds, or placement.
        """
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        if not isinstance(policy, RasterExtentPolicy):
            raise TypeError("policy must be RasterExtentPolicy")
        if not self._anchor_floating_pixels_before_edit():
            return False
        coordinator = self._raster_mutations
        return bool(
            coordinator is not None
            and coordinator.set_extent_policy(
                self._resolve_public_scene_id(scene_id),
                layer_id,
                policy,
            )
        )

    def requestRasterBounds(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        bounds: QRect,
    ) -> uuid.UUID | None:
        """Request an asynchronous pad/crop of raster-local storage bounds.

        Args:
            scene_id: Public or resolved identifier for the active scene.
            layer_id: Stable identifier of the raster layer to resize.
            bounds: Positive integer bounds in layer-local coordinates.

        Returns:
            A request UUID when the source accepted work, otherwise ``None``.

        Raises:
            TypeError: If identifiers or bounds use unsupported types.
            ValueError: If bounds do not have positive dimensions.

        Side effects:
            Emits ``rasterBoundsRequestCompleted`` after the request terminates.
        """
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        if not isinstance(bounds, QRect):
            raise TypeError("bounds must be a QRect")
        if bounds.width() <= 0 or bounds.height() <= 0:
            raise ValueError("bounds dimensions must be positive")
        if not self._anchor_floating_pixels_before_edit():
            return None
        coordinator = self._raster_mutations
        if coordinator is None:
            return None
        request_id = coordinator.request_bounds(
            self._resolve_public_scene_id(scene_id),
            layer_id,
            RasterBounds.from_qrect(bounds),
        )
        if request_id is not None:
            self._raster_request_public_scenes[request_id] = scene_id
        return request_id

    def deleteSelectedPixels(self) -> bool:
        """Clear selected coverage from the selected policy-enabled raster layer."""
        resolution = self.editorOperationResolver().resolve(
            EditorOperation.DELETE_PIXELS
        )
        return bool(
            resolution.allowed
            and resolution.layer_id is not None
            and self._anchor_floating_pixels_before_edit()
            and self.editorInteraction().delete_selected_pixels()
        )

    def floatingPixelEditState(self) -> FloatingPixelSnapshot | None:
        """Return detached state for the active unresolved floating-pixel edit."""
        movement = self._selected_pixel_movement
        if movement is None or not movement.active:
            return None
        scene_id = movement.scene_id
        source_layer_id = movement.source_layer_id
        if scene_id is None or source_layer_id is None:
            return None
        public_scene = self.currentScene()
        return FloatingPixelSnapshot(
            scene_id=(scene_id if public_scene is None else public_scene.scene_id),
            source_layer_id=source_layer_id,
            mode=(
                FloatingPixelMode.CUT if movement.cut_source else FloatingPixelMode.COPY
            ),
            offset=movement.offset,
            bounds=movement.scene_bounds,
        )

    def anchorFloatingPixels(
        self,
        scene_id: uuid.UUID | None = None,
        layer_id: uuid.UUID | None = None,
    ) -> bool:
        """Resolve floating pixels into their source or a compatible layer.

        Args:
            scene_id: Optional public destination scene identifier.
            layer_id: Optional destination layer identifier.

        Returns:
            True when an unresolved edit was resolved.

        Raises:
            TypeError: If supplied identifiers are not UUIDs.
            ValueError: If exactly one destination identifier is supplied.
        """
        if (scene_id is None) != (layer_id is None):
            raise ValueError("scene_id and layer_id must be supplied together")
        if scene_id is not None and not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID or None")
        if layer_id is not None and not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID or None")
        movement = self._editor_movement_interaction
        if movement is None:
            return False
        if scene_id is None:
            return movement.anchor_floating_pixels()
        return movement.anchor_floating_pixels_to(
            self._resolve_public_scene_id(scene_id),
            layer_id,
        )

    def promoteFloatingPixels(self, label: str | None = None) -> uuid.UUID | None:
        """Resolve floating pixels into a newly created compatible layer."""
        if label is not None and not isinstance(label, str):
            raise TypeError("label must be a string or None")
        movement = self._editor_movement_interaction
        return None if movement is None else movement.promote_floating_pixels(label)

    def cancelFloatingPixels(self) -> bool:
        """Discard an unresolved floating edit without changing source pixels."""
        movement = self._selected_pixel_movement
        return bool(movement is not None and movement.cancel())

    def sceneEditUndoAvailable(self) -> bool:
        """Return whether the active scene has an undoable composition edit."""
        movement = self._selected_pixel_movement
        if movement is not None and movement.active:
            return True
        service = self.mask_service
        active_mask_id = self.activeMaskID()
        if (
            service is not None
            and active_mask_id is not None
            and service.has_pending_stroke(active_mask_id)
        ):
            return True
        scene_id = self._active_resolved_scene_id()
        return bool(
            scene_id is not None
            and self.compositionService().edit_controller.can_undo(scene_id)
        )

    def sceneEditRedoAvailable(self) -> bool:
        """Return whether the active scene has a redoable composition edit."""
        movement = self._selected_pixel_movement
        if movement is not None and movement.active:
            return False
        service = self.mask_service
        active_mask_id = self.activeMaskID()
        if (
            service is not None
            and active_mask_id is not None
            and service.has_pending_stroke(active_mask_id)
        ):
            return False
        scene_id = self._active_resolved_scene_id()
        return bool(
            scene_id is not None
            and self.compositionService().edit_controller.can_redo(scene_id)
        )

    def undoSceneEdit(self) -> bool:
        """Undo the latest chronological editor change in the active scene."""
        movement = self._selected_pixel_movement
        if movement is not None and movement.active:
            if movement.offset.isNull():
                return movement.cancel()
            if not movement.anchor_to_source():
                return False
        scene_id = self._active_resolved_scene_id()
        if scene_id is None:
            return False
        service = self.mask_service
        active_mask_id = self.activeMaskID()
        if (
            service is not None
            and active_mask_id is not None
            and service.defer_history_action(
                active_mask_id,
                lambda: self._undo_scene_edit_scope(scene_id),
            )
        ):
            return True
        return self._undo_scene_edit_scope(scene_id)

    def _undo_scene_edit_scope(self, scene_id: uuid.UUID) -> bool:
        """Undo one exact scope after any asynchronous edit barrier clears."""
        return self.compositionService().edit_controller.undo(scene_id).changed

    def redoSceneEdit(self) -> bool:
        """Redo the next chronological editor change in the active scene."""
        movement = self._selected_pixel_movement
        if movement is not None and movement.active:
            return False
        scene_id = self._active_resolved_scene_id()
        if scene_id is None:
            return False
        return self.compositionService().edit_controller.redo(scene_id).changed
