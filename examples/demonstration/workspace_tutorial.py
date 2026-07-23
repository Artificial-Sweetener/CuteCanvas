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
the documents, layers, masks, persistence, and comparison state those commands
change.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Callable, Iterable
from pathlib import Path

from cutecanvas import ComparisonOrientation, CuteCanvas
from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QFileDialog, QWidget

from examples.demonstration import scene_composition
from examples.demonstration.workers import ImageLoaderWorker


class WorkspaceTutorialController:
    """Own user-facing content commands around one CuteCanvas facade."""

    def __init__(
        self,
        canvas: CuteCanvas,
        parent: QWidget,
        *,
        masks_available: Callable[[], bool],
        all_images_linked: Callable[[], bool],
        set_status: Callable[[str], None],
    ) -> None:
        """Retain the editor and narrow host policy callbacks."""
        self._canvas = canvas
        self._parent = parent
        self._masks_available = masks_available
        self._all_images_linked = all_images_linked
        self._set_status = set_status
        self._load_batch_auto_select = False

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

    def open_document_dialog(self) -> None:
        """Restore one complete editable CuteCanvas archive."""
        file_path, _ = QFileDialog.getOpenFileName(
            self._parent,
            "Open CuteCanvas Document",
            str(Path.home()),
            "CuteCanvas documents (*.cutecanvas)",
        )
        if not file_path:
            return
        try:
            document = self._canvas.editor.persistence.load(file_path)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self._set_status(f"Could not open document: {exc}")
            return
        self._set_status(f"Opened {document.state.title}.")

    def save_document_dialog(self) -> None:
        """Persist the active editable document as one atomic archive."""
        document = self._canvas.editor.documents.current
        if document is None:
            self._set_status("Open a document before saving.")
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self._parent,
            "Save CuteCanvas Document",
            str(Path.home() / f"{document.state.title}.cutecanvas"),
            "CuteCanvas documents (*.cutecanvas)",
        )
        if not file_path:
            return
        path = Path(file_path)
        if not path.suffix:
            path = path.with_suffix(".cutecanvas")
        try:
            self._canvas.editor.persistence.save(document, path)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self._set_status(f"Could not save document: {exc}")
            return
        self._set_status(f"Saved {document.state.title}.")

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
        worker = ImageLoaderWorker((Path(file_path),))
        worker.signals.image_loaded.connect(self.place_decoded_embedded_asset)
        worker.signals.finished.connect(
            lambda count: (
                self._set_status("The selected image could not be decoded.")
                if count == 0
                else None
            )
        )
        QThreadPool.globalInstance().start(worker)
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

    def clear_gallery(self) -> None:
        """Remove every gallery image through the public facade."""
        if self._canvas.hasImages():
            self._canvas.clearImages()
            self._set_status("Cleared all images.")

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
        """Export the active mask clipped to the document canvas."""
        if not self._require_masks():
            return
        mask_image = self._canvas.getActiveMaskImage()
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
        image_id = self._canvas.currentImageID()
        if image_id is None:
            self._set_status("Load an image before deleting masks.")
            return
        mask_id = self._canvas.activeMaskID()
        if mask_id is None:
            self._set_status("Select a mask to delete.")
            return
        if not self._canvas.removeMaskFromImage(image_id, mask_id):
            self._set_status("Unable to delete the selected mask.")
            return
        self._set_status("Deleted active mask layer.")

    def cycle_masks_forward(self) -> None:
        """Select the next mask in the active image stack."""
        self._canvas.cycleMasksForward()

    def cycle_masks_backward(self) -> None:
        """Select the previous mask in the active image stack."""
        self._canvas.cycleMasksBackward()

    def compare_with_next_image(self) -> None:
        """Reveal the next catalog image with a centered vertical divider."""
        image_ids = self._canvas.imageIDs()
        current_id = self._canvas.currentImageID()
        if current_id not in image_ids or len(image_ids) < 2:
            self._set_status("Load at least two images before comparing.")
            return
        next_id = image_ids[(image_ids.index(current_id) + 1) % len(image_ids)]
        self._canvas.setComparisonImageID(next_id)
        self._canvas.setComparisonSplit(0.5, ComparisonOrientation.VERTICAL)
        self._set_status(
            "Comparison enabled. Drag the image boundary to move the split."
        )

    def flip_compare_orientation(self) -> None:
        """Toggle the active comparison between vertical and horizontal."""
        state = self._canvas.comparisonState()
        orientation = (
            ComparisonOrientation.HORIZONTAL
            if state.orientation == ComparisonOrientation.VERTICAL
            else ComparisonOrientation.VERTICAL
        )
        self._canvas.setComparisonSplit(state.split_position, orientation)
        self._set_status(f"Comparison split: {orientation.value}.")

    def clear_comparison(self) -> None:
        """End comparison without changing the selected catalog image."""
        self._canvas.clearComparisonImage()
        self._set_status("Comparison cleared.")

    def compose_contact_sheet(self) -> None:
        """Build a stored contact-sheet composition from current resources."""
        image_ids = self._canvas.imageIDs()
        if not image_ids:
            self._set_status("Load images before composing a contact sheet.")
            return
        catalog = self._canvas.getCatalogSnapshot()
        request = scene_composition.build_contact_sheet_request(
            image_ids,
            image_sizes={
                image_id: catalog.catalog[image_id].image.size()
                for image_id in image_ids
            },
            columns=min(3, max(1, len(image_ids))),
            cell_width=320.0,
            cell_height=240.0,
            gap=16.0,
        )
        scene_composition.install_contact_sheet_overlay(self._canvas)
        composition_id = self._canvas.composeScene(request)
        self._set_status(f"Composed contact-sheet scene {composition_id}.")

    def step_image(self, delta: int) -> None:
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
        next_entry = snapshot.compositions.get(next_id)
        settings = self._canvas.settings.as_dict()
        if (
            next_entry is not None
            and next_entry.current_image_id is not None
            and bool(settings.get("mask_prefetch_enabled", False))
        ):
            self._canvas.prefetchMaskOverlays(
                next_entry.current_image_id, reason="step"
            )
        self._canvas.openComposition(next_id)
        self._set_status(
            f"Showing composition {next_index + 1} of {len(composition_ids)}."
        )

    def load_images(self, paths: Iterable[Path]) -> None:
        """Decode image files on QThreadPool before updating the catalog."""
        path_list = list(paths)
        if not path_list:
            return
        self.prepare_image_batch(len(path_list))
        worker = ImageLoaderWorker(path_list)
        worker.signals.image_loaded.connect(self.accept_decoded_image)
        worker.signals.finished.connect(self.finish_image_batch)
        QThreadPool.globalInstance().start(worker)

    def prepare_image_batch(self, count: int) -> None:
        """Prepare selection and status before an external decoder starts."""
        self._set_status(f"Queued {count} images for loading...")
        self._load_batch_auto_select = True

    def accept_decoded_image(self, path: Path, image: QImage) -> None:
        """Append one decoded image while preserving linked-view policy."""
        relink_all = self._all_images_linked()
        new_id = uuid.uuid4()
        current_id = self._canvas.currentImageID()
        if self._load_batch_auto_select:
            current_id = new_id
            self._load_batch_auto_select = False
        elif current_id is None:
            current_id = new_id
        image_map = CuteCanvas.imageMapFromLists(
            self._canvas.allImages + [image],
            self._canvas.allImagePaths + [path],
            self._canvas.imageIDs() + [new_id],
        )
        self._canvas.setImagesByID(image_map, current_id=current_id)
        if relink_all:
            self._canvas.setAllImagesLinked(True)
        self._set_status(f"Loaded {path.name}...")

    def finish_image_batch(self, count: int) -> None:
        """Announce completion of one background decode batch."""
        self._load_batch_auto_select = False
        total = len(self._canvas.imageIDs())
        self._set_status(
            f"Finished loading {count} images. Total: {total}. "
            "Use Left/Right to navigate compositions."
        )

    def remove_current_image(self) -> None:
        """Remove the active image and select the nearest surviving neighbor."""
        image_ids = self._canvas.imageIDs()
        if not image_ids:
            self._set_status("No images to remove.")
            return
        current_id = self._canvas.currentImageID() or image_ids[0]
        try:
            current_index = image_ids.index(current_id)
        except ValueError:
            current_index = 0
        remaining = image_ids[:current_index] + image_ids[current_index + 1 :]
        self._canvas.removeImageByID(current_id)
        if not remaining:
            self._set_status("Removed final image; viewer cleared.")
            return
        self._canvas.setCurrentImageID(
            remaining[min(current_index, len(remaining) - 1)]
        )
        self._set_status("Removed image; showing next entry.")

    def create_mask_for_current_image(
        self,
        *,
        announce: bool = True,
    ) -> uuid.UUID | None:
        """Create a blank image-sized mask and assign a visible demo color."""
        if not self._require_masks():
            return None
        image = self._canvas.currentImage
        if image is None or image.isNull():
            self._set_status("Load an image before creating masks.")
            return None
        mask_id = self._canvas.createBlankMask(image.size())
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
        image_id = self._canvas.currentImageID()
        if image_id is None:
            self._set_status("Load an image before selecting masks.")
            return
        mask_ids = self._canvas.maskIDsForImage(image_id)
        if not mask_ids:
            self._set_status("No masks on this image.")
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
        image = self._canvas.currentImage
        if image is None or image.isNull():
            self._set_status("Load an image before importing masks.")
            return
        mask_id = self._canvas.loadMaskFromFile(str(path))
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
