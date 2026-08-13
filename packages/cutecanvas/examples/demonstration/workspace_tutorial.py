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
"""Teach how host commands open, place, save, and arrange content.

The controller owns file dialogs and background image loading. CuteCanvas owns
the compositions, layers, masks, resources, and persistence those commands change.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Callable, Iterable
from pathlib import Path

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QFileDialog, QWidget

from cutecanvas import (
    CuteCanvas,
    ExecutionRuntime,
    LayerPolicy,
    prepare_document_restore,
)
from demonstration.document_saves import (
    DocumentSaveCoordinator,
    DocumentSaveResult,
)
from demonstration.workers import ImageLoadCoordinator


class WorkspaceTutorialController:
    """Own user-facing content commands around one CuteCanvas facade."""

    def __init__(
        self,
        canvas: CuteCanvas,
        parent: QWidget,
        *,
        execution_runtime: ExecutionRuntime,
        masks_available: Callable[[], bool],
        set_status: Callable[[str], None],
    ) -> None:
        """Retain the editor and narrow host policy callbacks."""
        self._canvas = canvas
        self._parent = parent
        self._masks_available = masks_available
        self._set_status = set_status
        self._load_batch_auto_select = False
        self._image_loads = ImageLoadCoordinator(execution_runtime, parent)
        self._document_saves = DocumentSaveCoordinator(
            execution_runtime,
            canvas.editor.persistence,
            parent,
        )
        self._image_compositions_by_path: dict[Path, uuid.UUID] = {}

    def close(self) -> None:
        """Cancel host-owned decoder work before the demo runtime shuts down."""
        self._image_loads.close()
        self._document_saves.close()

    @staticmethod
    def _ordinary_image_policy() -> LayerPolicy:
        """Return the demo policy for ordinary imported image layers."""
        return LayerPolicy(
            selectable=True,
            movable=True,
            pixel_editable=False,
            reorderable=True,
            removable=True,
        )

    def open_images_dialog(self) -> None:
        """Choose ordinary images and enqueue worker-side decoding."""
        files, _ = QFileDialog.getOpenFileNames(
            self._parent,
            "Open images",
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.gif *.webp)",
        )
        if files:
            self.load_images(Path(file_path) for file_path in files)

    def open_composition_dialog(self) -> None:
        """Restore one complete editable CuteCanvas archive."""
        file_path, _ = QFileDialog.getOpenFileName(
            self._parent,
            "Open CuteCanvas Composition",
            str(Path.home()),
            "CuteCanvas compositions (*.cutecanvas)",
        )
        if not file_path:
            return
        self.open_composition(Path(file_path))

    def open_composition(self, path: Path) -> bool:
        """Restore one complete editable CuteCanvas archive from a known path."""
        try:
            prepared = prepare_document_restore(path)
            compositions = self._canvas.editor.persistence.restore_document(prepared)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self._set_status(f"Could not open composition: {exc}")
            return False
        composition = compositions[0]
        self._set_status(f"Opened {composition.state.title}.")
        return True

    def save_composition_dialog(self) -> None:
        """Capture the complete workspace and persist it outside the GUI thread."""
        composition = self._canvas.editor.compositions.current
        if composition is None:
            self._set_status("Open a composition before saving.")
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self._parent,
            "Save CuteCanvas Workspace",
            str(Path.home() / f"{composition.state.title}.cutecanvas"),
            "CuteCanvas compositions (*.cutecanvas)",
        )
        if not file_path:
            return
        path = Path(file_path)
        if not path.suffix:
            path = path.with_suffix(".cutecanvas")
        try:
            snapshot = self._canvas.editor.persistence.capture_document()
        except (RuntimeError, TypeError, ValueError) as exc:
            self._set_status(f"Could not save composition: {exc}")
            return
        if not self._document_saves.submit(
            snapshot,
            path,
            finished=self._document_save_finished,
        ):
            self._set_status("That workspace destination is already being saved.")
            return
        self._set_status(f"Saving workspace to {path.name}…")

    def _document_save_finished(self, result: DocumentSaveResult) -> None:
        """Present one terminal background workspace save result."""
        if result.error is not None:
            self._set_status(f"Could not save workspace: {result.error}")
            return
        self._set_status(f"Saved workspace to {result.path.name}.")

    def place_embedded_dialog(self) -> None:
        """Decode one image off-thread before placing detached pixels."""
        file_path, _ = QFileDialog.getOpenFileName(
            self._parent,
            "Place Embedded Asset",
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.gif *.webp)",
        )
        if not file_path:
            return
        self._image_loads.submit(
            (Path(file_path),),
            image_loaded=self.place_decoded_embedded_asset,
            finished=lambda count: (
                self._set_status("The selected image could not be decoded.")
                if count == 0
                else None
            ),
        )
        self._set_status(f"Preparing embedded asset {Path(file_path).name}…")

    def place_linked_dialog(self) -> None:
        """Place one file-linked asset through CuteCanvas's async workflow."""
        file_path, _ = QFileDialog.getOpenFileName(
            self._parent,
            "Place Linked Asset",
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.gif *.webp)",
        )
        if not file_path:
            return
        request_id = self._canvas.placeLinkedAsset(
            Path(file_path),
            label=Path(file_path).stem,
        )
        if request_id is None:
            self._set_status("Open an image composition before placing an asset.")
            return
        self._set_status(f"Loading linked asset {Path(file_path).name}…")

    def close_all_compositions(self) -> None:
        """Remove every removable editor composition through typed handles."""
        compositions = tuple(self._canvas.editor.compositions)
        for composition in compositions:
            if composition.state.policy.removable:
                composition.remove()
        if compositions:
            self._set_status("Closed all removable compositions.")

    def add_mask(self) -> uuid.UUID | None:
        """Create and activate a visible blank mask for the current image."""
        return self.create_mask_for_current_image()

    def load_mask_dialog(self) -> None:
        """Choose one raster mask and import it into the active image."""
        if not self._require_masks():
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self._parent,
            "Import Mask",
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.gif *.webp)",
        )
        if file_path:
            self.import_mask_from_path(Path(file_path))

    def save_active_mask_dialog(self) -> None:
        """Export the active mask clipped to the composition canvas."""
        if not self._require_masks():
            return
        mask_id = self._canvas.activeMaskID()
        mask_image = None if mask_id is None else self._canvas.exportMaskImage(mask_id)
        if mask_image is None or mask_image.isNull():
            self._set_status("No active mask to save.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self._parent,
            "Save mask image",
            "mask.png",
            "PNG Images (*.png)",
        )
        if not path:
            return
        if not mask_image.save(path):
            self._set_status(f"Failed to save mask to {path}.")
            return
        self._set_status(f"Saved mask to {path}.")

    def delete_active_mask(self) -> None:
        """Delete the active mask after validating image and mask selection."""
        if not self._require_masks():
            return
        composition_id = self._canvas.currentCompositionID()
        if composition_id is None:
            self._set_status("Open a composition before deleting masks.")
            return
        mask_id = self._canvas.activeMaskID()
        if mask_id is None:
            self._set_status("Select a mask to delete.")
            return
        if not self._canvas.removeMaskFromComposition(composition_id, mask_id):
            self._set_status("Unable to delete the selected mask.")
            return
        self._set_status("Deleted active mask layer.")

    def cycle_masks_forward(self) -> None:
        """Select the next mask in the active image stack."""
        self._canvas.cycleMasksForward()

    def cycle_masks_backward(self) -> None:
        """Select the previous mask in the active image stack."""
        self._canvas.cycleMasksBackward()

    def place_next_composition(self) -> None:
        """Place another open composition as a reusable nested resource."""
        composition_ids = self._canvas.compositionIDs()
        current_id = self._canvas.currentCompositionID()
        candidates = [value for value in composition_ids if value != current_id]
        if current_id is None or not candidates:
            self._set_status("Open at least two compositions before placing one.")
            return
        source_id = candidates[0]
        layer_id = self._canvas.placeComposition(source_id)
        if layer_id is None:
            self._set_status("Unable to place the selected composition.")
            return
        self._set_status("Placed a live composition resource as a layer.")

    def step_composition(self, delta: int) -> None:
        """Move through compositions while preserving mask prefetch policy."""
        composition_ids = self._canvas.compositionIDs()
        if not composition_ids:
            self._set_status("Load an image first.")
            return
        current_id = self._canvas.currentCompositionID() or composition_ids[0]
        try:
            current_index = composition_ids.index(current_id)
        except ValueError:
            current_index = 0
        next_index = (current_index + delta) % len(composition_ids)
        next_id = composition_ids[next_index]
        snapshot = self._canvas.getCompositionSnapshot()
        settings = self._canvas.settings.as_dict()
        if next_id in snapshot.compositions and bool(
            settings.get("mask_prefetch_enabled", False)
        ):
            self._canvas.prefetchMaskOverlays(next_id, reason="step")
        self._canvas.openComposition(next_id)
        self._set_status(
            f"Showing composition {next_index + 1} of {len(composition_ids)}."
        )

    def load_images(self, paths: Iterable[Path]) -> None:
        """Decode image files off-thread before creating editor compositions."""
        path_list = list(paths)
        if not path_list:
            return
        self.prepare_image_batch(len(path_list))
        self._image_loads.submit(
            path_list,
            image_loaded=self.accept_decoded_image,
            finished=self.finish_image_batch,
        )

    def prepare_image_batch(self, count: int) -> None:
        """Prepare selection and status before an external decoder starts."""
        self._set_status(f"Queued {count} images for loading...")
        self._load_batch_auto_select = True

    def accept_decoded_image(self, path: Path, image: QImage) -> None:
        """Create one independent project composition from decoded pixels."""
        self._load_batch_auto_select = False
        normalized_path = path.resolve()
        existing_id = self._image_compositions_by_path.get(normalized_path)
        if existing_id is not None:
            self._canvas.document.replace_composition_image(existing_id, image)
            self._canvas.openComposition(existing_id)
            self._set_status(f"Refreshed {path.name}...")
            return
        composition_id = self._canvas.createCompositionFromImage(
            image,
            title=path.name,
            label=path.stem,
            interaction=self._ordinary_image_policy(),
        )
        self._image_compositions_by_path[normalized_path] = composition_id
        self._set_status(f"Loaded {path.name}...")

    def finish_image_batch(self, count: int) -> None:
        """Announce completion of one background decode batch."""
        self._load_batch_auto_select = False
        total = len(self._canvas.compositionIDs())
        self._set_status(
            f"Finished loading {count} images. Total: {total}. "
            "Use Left/Right to navigate compositions."
        )

    def remove_current_composition(self) -> None:
        """Close the active editor composition."""
        composition = self._canvas.editor.compositions.current
        if composition is None:
            self._set_status("No composition to close.")
            return
        composition.remove()
        self._set_status("Closed composition.")

    def create_mask_for_current_image(
        self,
        *,
        announce: bool = True,
    ) -> uuid.UUID | None:
        """Create a blank image-sized mask and assign a visible demo color."""
        if not self._require_masks():
            return None
        scene = self._canvas.currentScene()
        if scene is None or scene.bounds.isEmpty():
            self._set_status("Open a composition before creating masks.")
            return None
        mask_id = self._canvas.createBlankMask(
            scene.bounds.size().toSize(),
            undoable=True,
        )
        if mask_id is None:
            self._set_status("Unable to create a mask layer.")
            return None
        self._canvas.setMaskProperties(
            mask_id,
            color=QColor.fromHsv(random.randint(0, 359), 200, 255),
        )
        self._canvas.setActiveMaskID(mask_id)
        if announce:
            self._set_status(f"Mask created (ID: {mask_id}). Brush armed.")
        return mask_id

    def select_mask_by_index(self, index: int) -> None:
        """Activate one numbered mask slot when it exists."""
        if not self._masks_available():
            return
        composition_id = self._canvas.currentCompositionID()
        if composition_id is None:
            self._set_status("Open a composition before selecting masks.")
            return
        mask_ids = self._canvas.maskIDsForComposition(composition_id)
        if not mask_ids:
            self._set_status("No masks in this composition.")
            return
        if index >= len(mask_ids):
            self._set_status(f"Mask slot {index + 1} is empty.")
            return
        mask_id = mask_ids[index]
        self._canvas.setActiveMaskID(mask_id)
        self._set_status(f"Selected mask #{index + 1} (ID: {mask_id}).")

    def import_mask_from_path(self, path: Path) -> None:
        """Import and activate a raster mask through the public facade."""
        if not self._require_masks():
            return
        if self._canvas.currentCompositionID() is None:
            self._set_status("Open a composition before importing masks.")
            return
        mask_id = self._canvas.loadMaskFromFile(str(path), undoable=True)
        if mask_id is None:
            self._set_status(f"Failed to import mask from {path.name}.")
            return
        self._canvas.setActiveMaskID(mask_id)
        self._set_status(f"Imported mask layer from {path.name}.")

    def place_decoded_embedded_asset(self, path: Path, image: QImage) -> None:
        """Place one worker-decoded image and select its new layer."""
        layer_id = self._canvas.placeEmbeddedAsset(image, label=path.stem)
        scene = self._canvas.currentScene()
        if layer_id is None or scene is None:
            self._set_status("Open an image composition before placing an asset.")
            return
        self._canvas.setSelectedLayer(scene.scene_id, layer_id)
        self._set_status(f"Placed embedded asset {path.name}.")

    def _require_masks(self) -> bool:
        """Report that mask editing is unavailable in this canvas."""
        if self._masks_available():
            return True
        self._set_status("Mask tools disabled in this mode.")
        return False
