#    QPane - High-performance PySide6 image viewer
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
"""Teach asynchronous catalog and scene workflows through QPane's facade."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget
from qpane import ExecutionRuntime, QPane, ViewerCatalogEntry

from .catalog import CatalogPanel
from .loading import ViewerImageLoadCoordinator, ViewerImageProduct
from .scenes import ViewerSceneController
from .status import ViewerStatusBar

_IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff)"


class ViewerWorkspaceController:
    """Own host catalog commands and asynchronous image-loader lifetimes."""

    def __init__(
        self,
        pane: QPane,
        parent: QWidget,
        *,
        execution_runtime: ExecutionRuntime,
        catalog_panel: CatalogPanel,
        scenes: ViewerSceneController,
        status: ViewerStatusBar,
        refresh_commands: Callable[[], None],
        reveal_catalog: Callable[[], None],
    ) -> None:
        """Capture host collaborators while leaving render state in QPane."""
        self._pane = pane
        self._parent = parent
        self._catalog = pane.catalog()
        self._catalog_panel = catalog_panel
        self._scenes = scenes
        self._status = status
        self._refresh_commands = refresh_commands
        self._reveal_catalog = reveal_catalog
        self._image_loads = ViewerImageLoadCoordinator(execution_runtime, parent)

    def add_image(
        self,
        image: QImage,
        *,
        label: str = "Untitled",
        path: Path | None = None,
    ) -> ViewerCatalogEntry:
        """Add decoded pixels, prepare a thumbnail, and select the new entry."""
        entry = self._pane.addImage(image, label=label, path=path, select=False)
        thumbnail = image.scaled(
            144,
            96,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._catalog_panel.set_thumbnail(entry.entry_id, thumbnail)
        self._pane.selectCatalogImage(entry.entry_id)
        return entry

    def open_images(self, _checked: bool = False) -> None:
        """Choose and asynchronously decode one or more large images."""
        names, _selected_filter = QFileDialog.getOpenFileNames(
            self._parent,
            "Open images",
            "",
            _IMAGE_FILTER,
        )
        if not names:
            return
        paths = tuple(Path(name) for name in names)
        self._image_loads.submit(
            paths,
            loaded=self.accept_loaded_image,
            failed=self.report_load_failure,
            finished=lambda: self._status.showMessage(
                f"Finished loading {len(paths)} image(s)"
            ),
        )
        self._status.showMessage(f"Loading {len(paths)} image(s)…")

    def accept_loaded_image(
        self,
        product: ViewerImageProduct,
    ) -> None:
        """Promote one worker result into GUI-owned catalog state."""
        entry = self._pane.addImage(
            product.image,
            label=product.path.name,
            path=product.path,
            select=False,
        )
        self._catalog_panel.set_thumbnail(entry.entry_id, product.thumbnail)
        self._pane.selectCatalogImage(entry.entry_id)
        self._status.showMessage(f"Loaded image: {product.path.name}")

    def report_load_failure(self, path: Path, reason: str) -> None:
        """Report one decoding failure without disrupting successful entries."""
        QMessageBox.warning(
            self._parent,
            "Unable to open image",
            f"{path}\n\n{reason}",
        )

    def show_catalog_entry(self, entry: ViewerCatalogEntry | None) -> None:
        """Reflect QPane's already-presented catalog selection in host status."""
        if entry is not None:
            self._status.showMessage(f"Viewing {entry.label}")

    def reactivate_catalog_entry(self, entry: ViewerCatalogEntry | None) -> None:
        """Restore presentation when the selected catalog row is activated again."""
        if entry is not None:
            self._pane.selectCatalogImage(entry.entry_id)
            self.show_catalog_entry(entry)

    def handle_catalog_changed(self) -> None:
        """Refresh commands and reveal useful multi-image navigation."""
        if len(self._catalog.entries) > 1:
            self._reveal_catalog()
        self._refresh_commands()

    def previous_image(self, _checked: bool = False) -> None:
        """Select the previous catalog image with wraparound."""
        self._pane.selectPreviousImage()

    def next_image(self, _checked: bool = False) -> None:
        """Select the next catalog image with wraparound."""
        self._pane.selectNextImage()

    def remove_current(self, _checked: bool = False) -> None:
        """Remove the active image from the host catalog."""
        removed = self._catalog.current
        if removed is not None:
            self._pane.removeCatalogImage(removed.entry_id)
            self._catalog_panel.discard_thumbnail(removed.entry_id)
            self._status.showMessage(f"Removed {removed.label}")

    def clear_catalog(self, _checked: bool = False) -> None:
        """Clear viewer resources and return to the blank canvas."""
        self._pane.clearCatalog()
        self._status.showMessage("Catalog cleared. Press Ctrl+O to load images.")

    def compare_next(self, _checked: bool = False) -> None:
        """Reveal the next catalog image over the current one."""
        if self._scenes.compare_with_next():
            self._status.showMessage("Comparing current and next image")
        self._refresh_commands()

    def flip_compare(self, _checked: bool = False) -> None:
        """Flip the active comparison divider orientation."""
        if self._scenes.flip_comparison():
            orientation = self._scenes.comparison_orientation.value
            self._status.showMessage(f"Comparison divider: {orientation}")
        self._refresh_commands()

    def clear_compare(self, _checked: bool = False) -> None:
        """Dismiss comparison and return to the active image."""
        self._scenes.clear_comparison()
        self._refresh_commands()

    def compose_contact_sheet(self, _checked: bool = False) -> None:
        """Show every reusable catalog source in one declarative scene."""
        if self._scenes.compose_contact_sheet():
            self._status.showMessage("Composed catalog contact sheet")

    def show_sdk_scene(self, _checked: bool = False) -> None:
        """Open the secondary raster/vector rendering SDK lesson."""
        self._scenes.show_sdk_scene()
        self._status.showMessage(
            "Rendering SDK scene: raster and semantic vector sources"
        )

    def copy_current_image(self, _checked: bool = False) -> None:
        """Copy the current raster and report whether content existed."""
        if self._pane.copyCurrentImageToClipboard():
            self._status.showMessage("Copied current image")
        else:
            self._status.showMessage("No raster image is available to copy")

    def close(self) -> None:
        """Cancel host-owned decoder work before runtime shutdown."""
        self._image_loads.close()
