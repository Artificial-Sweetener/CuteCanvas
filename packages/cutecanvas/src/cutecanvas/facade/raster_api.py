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
    QRect,
    QRectF,
    QSize,
)
from PySide6.QtGui import (
    QColor,
    QImage,
)
from qpane.sdk.raster import (
    qimage_to_numpy_grayscale8,
)
from qpane.sdk.scene import RasterBounds

from cutecanvas.composition.public_policy import (
    internal_layer_policy,
)
from cutecanvas.coverage import CoverageCombineMode, CoverageSnapshot
from cutecanvas.editor import (
    EditorOperation,
)
from cutecanvas.painting import BrushPreset
from cutecanvas.raster.source_reference import EditableRasterReference
from cutecanvas.types import (
    FloatingPixelMode,
    FloatingPixelSnapshot,
    LayerPolicy,
    PaintTargetSnapshot,
    PixelSelectionMode,
    PixelSelectionSnapshot,
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
        """Add a detached editable color raster to the active image scene.

        Args:
            image: Non-null color raster copied into composition-owned storage.
            placement: Optional scene placement; source dimensions are used by default.
            label: Optional host-facing layer label.
            interaction: Host policy for selection, movement, and pixel editing.
            extent_policy: Fixed, expanding, or unbounded future write behavior.

        Returns:
            The stable layer UUID, or ``None`` when no catalog image is active.
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
        image = QImage(initial_size, QImage.Format_ARGB32_Premultiplied)
        image.fill(QColor(0, 0, 0, 0))
        layer_id = self.addEditableRasterLayer(
            image,
            label=label,
            interaction=LayerPolicy(
                selectable=True,
                movable=True,
                pixel_editable=True,
            ),
            extent_policy=extent_policy,
        )
        if layer_id is not None:
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
                lambda layer: layer.scene_id == identity.scene_id
                and layer.layer_id == identity.layer_id
            )
            if resolved is None:
                return None
            source_kind = resolved[1].source.kind
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
        return self.paintingCoordinator().select_layer(
            self._resolve_public_scene_id(scene_id),
            layer_id,
        )

    def setPixelSelectionPaintTarget(self) -> bool:
        """Select the active composition's pixel-selection coverage for painting."""
        scene_id = self._active_resolved_scene_id()
        return bool(
            scene_id is not None
            and self.paintingCoordinator().select_pixel_selection(scene_id)
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
            resolved[1].source, EditableRasterReference
        ):
            return None
        assets = self._editable_raster_assets
        asset = None if assets is None else assets.get(resolved[1].source.raster_id)
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

    def pixelSelectionState(self) -> PixelSelectionSnapshot | None:
        """Return the active composition's detached pixel-selection state."""
        scene_id = self._active_resolved_scene_id()
        if scene_id is None:
            return None
        return self._public_pixel_selection_state(
            self.editorInteraction().pixel_selection_state(scene_id)
        )

    def setPixelSelection(
        self,
        coverage: QImage,
        bounds: QRect,
        mode: PixelSelectionMode = PixelSelectionMode.REPLACE,
    ) -> bool:
        """Combine grayscale coverage into the active composition selection.

        Args:
            coverage: Grayscale or color image interpreted as selection coverage.
            bounds: Scene-coordinate bounds occupied by ``coverage``.
            mode: Replacement, addition, subtraction, or intersection behavior.

        Returns:
            True when active selection state changed.

        Raises:
            TypeError: If inputs use unsupported public types.
            ValueError: If coverage is null or dimensions do not match bounds.
        """
        if not isinstance(coverage, QImage):
            raise TypeError("coverage must be a QImage")
        if not isinstance(bounds, QRect):
            raise TypeError("bounds must be a QRect")
        if not isinstance(mode, PixelSelectionMode):
            raise TypeError("mode must be PixelSelectionMode")
        if coverage.isNull():
            raise ValueError("coverage must not be null")
        if (
            coverage.size() != bounds.size()
            or bounds.width() <= 0
            or bounds.height() <= 0
        ):
            raise ValueError("coverage dimensions must match positive bounds")
        scene_id = self._active_resolved_scene_id()
        resolution = self.editorOperationResolver().resolve(
            EditorOperation.SELECT_PIXELS
        )
        if (
            scene_id is None
            or not resolution.allowed
            or not self._anchor_floating_pixels_before_edit()
        ):
            return False
        return self.editorInteraction().commit_pixel_selection(
            scene_id,
            CoverageSnapshot(
                bounds=RasterBounds.from_qrect(bounds),
                extent_policy=RasterExtentPolicy.EXPAND_ON_WRITE,
                pixels=qimage_to_numpy_grayscale8(coverage),
            ),
            CoverageCombineMode(mode.value),
        )

    def clearPixelSelection(self) -> bool:
        """Clear pixel selection in the active composition."""
        scene_id = self._active_resolved_scene_id()
        return bool(
            scene_id is not None
            and self._anchor_floating_pixels_before_edit()
            and self.editorInteraction().clear_pixel_selection(scene_id)
        )

    def selectAllPixels(self) -> bool:
        """Select every pixel inside the active scene's finite canvas bounds."""
        scene_id = self._active_resolved_scene_id()
        resolution = self.editorOperationResolver().resolve(
            EditorOperation.SELECT_PIXELS
        )
        return bool(
            scene_id is not None
            and resolution.allowed
            and self._anchor_floating_pixels_before_edit()
            and self.editorInteraction().select_all_pixels(scene_id)
        )

    def invertPixelSelection(self) -> bool:
        """Invert pixel selection inside the active scene's finite canvas bounds."""
        scene_id = self._active_resolved_scene_id()
        resolution = self.editorOperationResolver().resolve(
            EditorOperation.SELECT_PIXELS
        )
        return bool(
            scene_id is not None
            and resolution.allowed
            and self._anchor_floating_pixels_before_edit()
            and self.editorInteraction().invert_pixel_selection(scene_id)
        )

    def selectLayerCoverage(
        self,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        mode: PixelSelectionMode = PixelSelectionMode.REPLACE,
    ) -> bool:
        """Use a coverage-producing layer as composition pixel selection."""
        if not isinstance(scene_id, uuid.UUID):
            raise TypeError("scene_id must be a UUID")
        if not isinstance(layer_id, uuid.UUID):
            raise TypeError("layer_id must be a UUID")
        if not isinstance(mode, PixelSelectionMode):
            raise TypeError("mode must be PixelSelectionMode")
        resolution = self.editorOperationResolver().resolve(
            EditorOperation.SELECT_PIXELS
        )
        if not resolution.allowed or not self._anchor_floating_pixels_before_edit():
            return False
        return self.editorInteraction().select_layer_coverage(
            self._resolve_public_scene_id(scene_id),
            layer_id,
            CoverageCombineMode(mode.value),
        )

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
        result = self.compositionService().edit_controller.undo(scene_id)
        if result.changed:
            self._publish_scene_layer_change()
        return result.changed

    def redoSceneEdit(self) -> bool:
        """Redo the next chronological editor change in the active scene."""
        movement = self._selected_pixel_movement
        if movement is not None and movement.active:
            return False
        scene_id = self._active_resolved_scene_id()
        if scene_id is None:
            return False
        result = self.compositionService().edit_controller.redo(scene_id)
        if result.changed:
            self._publish_scene_layer_change()
        return result.changed
