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
"""InteractionApi behavior for the CuteCanvas facade."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Mapping

from PySide6.QtCore import (
    QSize,
)
from PySide6.QtGui import (
    QColor,
)
from qpane.sdk.catalog import ImageMap
from qpane.sdk.overlays import SceneOverlayDrawFn
from qpane.sdk.types import (
    CatalogEntry,
    ComparisonDividerState,
    ComparisonOrientation,
    ComparisonState,
    LinkedGroup,
)

from cutecanvas.core import (
    CursorProvider,
    ToolFactory,
    ToolSignalBinder,
)
from cutecanvas.tools import Tools
from cutecanvas.types import (
    CatalogSnapshot,
)

logger = logging.getLogger(__name__)


class InteractionApiMixin:
    """Group interactionapi facade behavior."""

    def registerSceneOverlay(
        self,
        name: str,
        draw_fn: SceneOverlayDrawFn,
    ) -> None:
        """Register a scene overlay painted relative to layered scene composition layers.

        Raises:
            ValueError: If `name` is already present.
        """
        self.interaction.registerSceneOverlay(name, draw_fn)

    def unregisterSceneOverlay(self, name: str) -> None:
        """Remove a previously registered scene overlay."""
        self.interaction.unregisterSceneOverlay(name)

    def sceneOverlays(self) -> Mapping[str, SceneOverlayDrawFn]:
        """Return a read-only snapshot of registered scene overlays."""
        return self.interaction.scene_overlays_snapshot()

    def overlaysSuspended(self) -> bool:
        """Return True when interaction-managed overlays are currently suppressed."""
        return self.interaction.overlays_suspended

    def overlaysResumePending(self) -> bool:
        """Indicate overlays should resume once pending activation work finishes."""
        return self.interaction.overlays_resume_pending

    def resumeOverlays(self) -> None:
        """Allow overlay drawing to resume on the next paint."""
        self.interaction.resume_overlays()

    def resumeOverlaysAndUpdate(self) -> None:
        """Resume overlays and trigger a repaint."""
        self.interaction.resume_overlays_and_update()

    def maybeResumeOverlays(self) -> None:
        """Resume overlays when activation has completed for the active image."""
        self.interaction.maybe_resume_overlays()

    def registerCursorProvider(self, mode: str, provider: CursorProvider) -> None:
        """Attach a cursor provider via the supported facade helper.

        If the mode is active when this is called, the cursor updates immediately.
        """
        self.interaction.registerCursorProvider(mode, provider)

    def unregisterCursorProvider(self, mode: str) -> None:
        """Detach a previously registered cursor provider."""
        self.interaction.unregisterCursorProvider(mode)

    def registerTool(
        self,
        mode: str,
        factory: ToolFactory,
        *,
        on_connect: ToolSignalBinder | None = None,
        on_disconnect: ToolSignalBinder | None = None,
    ) -> None:
        """Register a custom control mode through the supported facade API.

        Args:
            mode: Unique identifier for the tool mode.
            factory: Callable that creates a tool instance when the mode activates.
            on_connect: Optional binder for wiring tool-specific signals.
            on_disconnect: Optional binder invoked during teardown to unwire signals.
        """
        self.hooks.registerTool(
            mode,
            factory,
            on_connect=on_connect,
            on_disconnect=on_disconnect,
        )

    def unregisterTool(self, mode: str) -> None:
        """Remove a previously registered tool mode via the supported facade."""
        self.hooks.unregisterTool(mode)

    def setImagesByID(
        self,
        image_map: ImageMap,
        current_id: uuid.UUID,
    ):
        """Replace the catalog contents and navigate to ``current_id`` via the facade."""
        self._cancel_floating_pixels_for_context_change()
        catalog = self.catalog()
        removed_image_ids = tuple(set(catalog.imageIDs()) - set(image_map))
        self._masks_controller.prepare_catalog_image_removal(removed_image_ids)
        catalog.setImagesByID(image_map, current_id)
        self._sync_compositions_with_catalog()
        if current_id in self.catalog().imageIDs():
            self._activate_default_composition_for_image(current_id)

    def clearImages(self):
        """Reset the catalog, linked views, and caches before showing the configured placeholder."""
        self._cancel_floating_pixels_for_context_change()
        catalog = self.catalog()
        self._masks_controller.prepare_catalog_image_removal(tuple(catalog.imageIDs()))
        catalog.clearImages()
        self._scene_selection.clear()
        if self.compositionService().clear():
            self._emit_composition_changed()
            self._emit_composition_selection_changed(None)
            self._emit_scene_changed()

    def removeImageByID(self, image_id: uuid.UUID):
        """Remove ``image_id`` when present; callers remain responsible for navigation."""
        self._cancel_floating_pixels_for_context_change()
        catalog = self.catalog()
        self._masks_controller.prepare_catalog_image_removal((image_id,))
        catalog.removeImageByID(image_id)
        self._sync_compositions_with_catalog()

    def removeImagesByID(self, image_ids: list[uuid.UUID]):
        """Remove the provided image IDs when present without selecting a fallback."""
        self._cancel_floating_pixels_for_context_change()
        catalog = self.catalog()
        self._masks_controller.prepare_catalog_image_removal(tuple(image_ids))
        catalog.removeImagesByID(image_ids)
        self._sync_compositions_with_catalog()

    def setCurrentImageID(self, image_id: uuid.UUID | None):
        """Navigate to ``image_id`` while overlays are suspended for navigation.

        If ``image_id`` is None, the current image is deselected and the qpane
        reverts to its configured fallback state (placeholder or blank).
        """
        self._cancel_floating_pixels_for_context_change()
        self.interaction.suspend_overlays_for_navigation()
        catalog = self.catalog()
        catalog.setCurrentImageID(image_id)
        if image_id is None:
            if self.compositionService().clear_selection():
                self._emit_composition_selection_changed(None)
                self._emit_scene_changed()
            self._emit_catalog_selection_changed(None)
            self._handle_comparison_changed()
        elif catalog.currentImageID() == image_id:
            self._activate_default_composition_for_image(image_id)

    def setAllImagesLinked(self, enabled: bool):
        """Toggle pan/zoom synchronization across all images."""
        image_ids = self.catalog().imageIDs()
        if enabled and len(image_ids) >= 2:
            members = tuple(image_ids)
            existing = self.linkedGroups()
            reuse_id = None
            for group in existing:
                if set(group.members) == set(members):
                    reuse_id = group.group_id
                    break
            group_id = reuse_id if reuse_id is not None else uuid.uuid4()
            self.setLinkedGroups((LinkedGroup(group_id=group_id, members=members),))
        else:
            self.setLinkedGroups(())

    def setLinkedGroups(self, groups: Iterable[LinkedGroup]) -> None:
        """Define linked pan/zoom groups and emit link change signals.

        Args:
            groups: LinkedGroup definitions to persist.

        Side effects:
            Emits ``linkGroupsChanged`` when the group definition changes.
        """
        self.linkManager().setGroups(tuple(groups))
        self._maybe_emit_link_groups_changed()

    def compose(
        self,
        *,
        images: Iterable[uuid.UUID],
        title: str | None = None,
    ) -> uuid.UUID:
        """Create and open a persistent composition from catalog image IDs.

        Args:
            images: One or two catalog image UUIDs in composition order.
            title: Optional host-facing title.

        Raises:
            KeyError: If any image ID is not in the catalog.
            ValueError: If the image list is empty, too long, or duplicated.

        Side effects:
            Opens the new composition, updates catalog selection to its base
            image, emits composition signals, and refreshes comparison state.
        """
        image_ids = tuple(images)
        missing = [
            image_id
            for image_id in image_ids
            if not self._image_catalog.containsImage(image_id)
        ]
        if missing:
            raise KeyError("compose image IDs must exist in the catalog")
        record = self.compositionService().compose(
            image_ids,
            title=title,
            path_lookup=self.imagePath,
        )
        self._open_composition_record(record)
        self._emit_composition_changed()
        return record.composition_id

    def openComposition(self, composition_id: uuid.UUID) -> None:
        """Open an existing composition by UUID.

        Args:
            composition_id: Composition UUID returned by composition APIs.

        Raises:
            KeyError: If ``composition_id`` is unknown.
            TypeError: If ``composition_id`` is not a UUID.

        Side effects:
            Updates the effective catalog selection and emits composition
            selection/comparison state.
        """
        record = self.compositionService().open_composition(composition_id)
        self._open_composition_record(record)

    def removeComposition(self, composition_id: uuid.UUID) -> None:
        """Remove a composition when its document policy permits removal.

        Raises:
            ValueError: If document policy prevents removal.
            KeyError: If ``composition_id`` is unknown.

        Side effects:
            Emits composition change signals and opens the next available
            composition when the removed one was active.
        """
        service = self.compositionService()
        previous_id = service.current_composition_id()
        service.remove_composition(composition_id)
        active = service.active_record()
        if previous_id == composition_id and active is not None:
            self._open_composition_record(active)
        elif active is None:
            self.setCurrentImageID(None)
        self._emit_composition_changed()

    def getCatalogSnapshot(self) -> CatalogSnapshot:
        """Return a structured catalog snapshot for host consumption.

        Returns:
            CatalogSnapshot: Ordered catalog entries, linked groups, and active IDs.
        """
        image_ids = tuple(self.imageIDs())
        all_images = self.allImages
        all_paths = self.allImagePaths
        catalog_entries: dict[uuid.UUID, CatalogEntry] = {}
        for image_id, image, path in zip(image_ids, all_images, all_paths):
            catalog_entries[image_id] = CatalogEntry(image=image, path=path)
        return CatalogSnapshot(
            catalog=catalog_entries,
            linked_groups=tuple(self.linkedGroups()),
            order=image_ids,
            current_image_id=self.currentImageID(),
            active_mask_id=self.activeMaskID(),
            mask_capable=self.maskFeatureAvailable(),
        )

    def createBlankMask(self, size: QSize) -> uuid.UUID | None:
        """Create an empty mask layer in the active composition.

        Args:
            size: Dimensions of the new mask in local raster pixels.

        Returns:
            The new mask UUID, or None when mask tooling is unavailable.

        Side effects:
            Emits ``catalogChanged`` with ``maskCreated`` when a mask is created.
        """
        mask_id = self._masks_controller.create_blank_mask(size)
        if mask_id is not None:
            self._emit_catalog_mutation("maskCreated", affected_ids=(mask_id,))
        return mask_id

    def loadMaskFromFile(self, path: str) -> uuid.UUID | None:
        """Load a mask layer from disk and return its ID when available.

        Side effects:
            Emits ``catalogChanged`` with ``maskImported`` when a mask is loaded.
        """
        mask_id = self._masks_controller.load_mask_from_file(path)
        if mask_id is not None:
            self._emit_catalog_mutation("maskImported", affected_ids=(mask_id,))
        return mask_id

    def removeMaskFromImage(self, image_id: uuid.UUID, mask_id: uuid.UUID) -> bool:
        """Remove `mask_id` from `image_id` through the active mask service.

        Side effects:
            Emits ``catalogChanged`` with ``maskDeleted`` when removal succeeds.
            Emits ``catalogSelectionChanged`` for the active image when removal succeeds.
        """
        self._cancel_floating_pixels_for_context_change()
        removed = self._masks_controller.remove_mask_from_image(image_id, mask_id)
        if removed:
            self._emit_catalog_mutation("maskDeleted", affected_ids=(mask_id,))
            self._emit_catalog_selection_changed(image_id)
        return removed

    def setActiveMaskID(self, mask_id: uuid.UUID | None) -> bool:
        """Set and synchronize the active mask's generic editing destination."""
        self._cancel_floating_pixels_for_context_change()
        changed = self._masks_controller.set_active_mask_id(mask_id)
        if changed:
            self._synchronize_active_mask_layer_selection()
            current_id = None
            try:
                current_id = self.catalog().currentImageID()
            except RuntimeError:
                current_id = None
            self._emit_catalog_selection_changed(current_id)
        return changed

    def setMaskProperties(
        self,
        mask_id: uuid.UUID,
        color: QColor | None = None,
        opacity: float | None = None,
    ) -> bool:
        """Update display properties for ``mask_id``.

        Args:
            mask_id: Identifier of the mask to update.
            color: New color when provided; leave unchanged when None.
            opacity: New opacity when provided; leave unchanged when None.

        Returns:
            True when mask presentation changed.
        """
        changed = self._masks_controller.set_mask_properties(
            mask_id, color=color, opacity=opacity
        )
        if changed:
            self._emit_catalog_mutation(
                "maskPropertiesChanged", affected_ids=(mask_id,)
            )
        return changed

    def prefetchMaskOverlays(
        self, image_id: uuid.UUID | None, *, reason: str = "navigation"
    ) -> bool:
        """Request asynchronous warming of mask renders for `image_id` when masking is available."""
        return self._masks_controller.prefetch_mask_overlays(image_id, reason=reason)

    def cycleMasksForward(self):
        """Cycle the mask layer stack forward, moving the bottom layer to the top."""
        self._cancel_floating_pixels_for_context_change()
        return self._masks_controller.cycle_masks_forward()

    def cycleMasksBackward(self):
        """Cycle the mask layer stack backward, moving the top layer to the bottom."""
        self._cancel_floating_pixels_for_context_change()
        return self._masks_controller.cycle_masks_backward()

    def undoMaskEdit(self) -> bool:
        """Undo the last mask edit through the mask workflow."""
        movement = self._selected_pixel_movement
        if movement is not None and movement.active:
            return self.undoSceneEdit()
        return self._masks_controller.undo_mask_edit()

    def redoMaskEdit(self) -> bool:
        """Redo the last reverted mask edit through the mask workflow."""
        movement = self._selected_pixel_movement
        if movement is not None and movement.active:
            return False
        return self._masks_controller.redo_mask_edit()

    def setControlMode(
        self,
        mode: str,
    ):
        """Delegate control-mode changes to the interaction layer."""
        if self.catalog().placeholderActive():
            mask_modes = {
                Tools.CONTROL_MODE_DRAW_BRUSH,
                Tools.CONTROL_MODE_PAINT_BUCKET,
                Tools.CONTROL_MODE_MASK_RECTANGLE,
                Tools.CONTROL_MODE_MASK_ELLIPSE,
                Tools.CONTROL_MODE_MASK_LASSO,
                Tools.CONTROL_MODE_SMART_SELECT,
            }
            if mode in mask_modes:
                logger.info(
                    "Ignoring mask control mode while placeholder is active: %s", mode
                )
                return
        self.interaction.set_control_mode(mode)

    def setComparisonImageID(self, image_id: uuid.UUID) -> None:
        """Use a catalog image as the comparison reveal source.

        Args:
            image_id: Catalog UUID to render as the comparison image.

        Raises:
            KeyError: If ``image_id`` is not in the catalog.
            TypeError: If ``image_id`` is not a UUID.

        Side effects:
            Marks the rendered scene dirty and emits ``comparisonChanged``.
        """
        self._comparison_service().set_catalog_image(image_id)

    def clearComparisonImage(self) -> None:
        """Disable comparison rendering and repaint the current scene."""
        self._comparison_service().clear()

    def setComparisonSplit(
        self,
        position: float,
        orientation: ComparisonOrientation | str | None = None,
    ) -> None:
        """Set the comparison reveal split.

        Args:
            position: Normalized split position from ``0.0`` to ``1.0``.
            orientation: Optional split orientation.

        Raises:
            ValueError: If ``position`` is not numeric or orientation is unknown.

        Side effects:
            Marks the rendered scene dirty and emits ``comparisonChanged``.
        """
        self._comparison_service().set_split(position, orientation)

    def comparisonState(self) -> ComparisonState:
        """Return the current comparison rendering state."""
        return self._comparison_service().state()

    def comparisonDividerInteractive(self) -> bool:
        """Return whether comparison-divider dragging is enabled."""
        return self.comparisonDividerInteraction().interactive()

    def setComparisonDividerInteractive(self, enabled: bool) -> None:
        """Enable or disable built-in comparison-divider dragging.

        Args:
            enabled: Whether the split boundary should accept mouse drags while
                comparison rendering is active.

        Raises:
            TypeError: If ``enabled`` is not a bool.

        Side effects:
            Clears any active divider drag, refreshes the cursor, and schedules a
            repaint.
        """
        self.comparisonDividerInteraction().set_interactive(enabled)
        self.refreshCursor()
        self.update()

    def comparisonDividerState(self) -> ComparisonDividerState:
        """Return host-facing comparison divider geometry and interaction state."""
        return self.comparisonDividerInteraction().state()
