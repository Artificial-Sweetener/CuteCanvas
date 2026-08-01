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
"""Assemble the polished QPane viewer tutorial from focused host owners.

The entrypoint intentionally reads in the order an integrator would build a
viewer: create QPane, add a catalog presenter, wire workspace commands, and
then connect the surrounding status and menu chrome.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QIcon, QImage
from PySide6.QtWidgets import QMainWindow, QSplitter, QVBoxLayout, QWidget

from qpane import QPane, ViewerCatalogEntry, create_default_execution_runtime

from .catalog import CatalogPanel
from .commands import ViewerCommandController
from .extensions import InspectionTool
from .scenes import ViewerSceneController
from .status import ViewerStatusBar
from .workspace import ViewerWorkspaceController

_INSPECTION_MODE = "inspect"


class ViewerWindow(QMainWindow):
    """Present the catalog-oriented QPane viewer experience."""

    def __init__(self) -> None:
        """Build the empty viewer, tutorial owners, and familiar host chrome."""
        super().__init__()
        self.setWindowTitle("QPane Example")
        self.resize(1280, 900)
        self._apply_window_icon()
        self._execution_runtime = create_default_execution_runtime()
        self._execution_closed = False
        self.pane = QPane(execution_runtime=self._execution_runtime)
        self.pane.setObjectName("qpaneViewer")
        self.pane.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.pane.registerTool(
            _INSPECTION_MODE,
            lambda: InspectionTool(self.pane),
        )
        self.catalog = self.pane.catalog()
        self.scenes = ViewerSceneController(self.pane, self.catalog, self)
        self.catalog_panel = CatalogPanel(self.catalog)
        self._build_layout()
        self.status = ViewerStatusBar()
        self.setStatusBar(self.status)
        self.workspace = ViewerWorkspaceController(
            self.pane,
            self,
            execution_runtime=self._execution_runtime,
            catalog_panel=self.catalog_panel,
            scenes=self.scenes,
            status=self.status,
            refresh_commands=lambda: self.commands.update_action_states(),
            reveal_catalog=lambda: self.commands.reveal_catalog_automatically(),
        )
        self.commands = ViewerCommandController(
            self.pane,
            self,
            workspace=self.workspace,
            scenes=self.scenes,
            catalog_panel=self.catalog_panel,
            status=self.status,
            catalog_container=self._catalog_container,
            splitter=self._splitter,
        )
        self.status.zoomRequested.connect(self.pane.applyZoom)
        self.status.zoomPresetRequested.connect(self.commands.apply_zoom_preset)
        self.pane.customContextMenuRequested.connect(self.commands.show_canvas_menu)
        self.commands.connect_signals()
        self.commands.prime()
        self.status.showMessage("Right-click canvas or press Ctrl+O to load images.")

    def addImage(
        self,
        image: QImage,
        *,
        label: str = "Untitled",
        path: Path | None = None,
    ) -> ViewerCatalogEntry:
        """Add an already-decoded image through the tutorial workspace.

        Args:
            image: Non-null image owned by the calling host.
            label: Human-readable catalog label.
            path: Optional source path used only for presentation.

        Returns:
            The new catalog entry and reusable raster source owner.
        """
        return self.workspace.add_image(image, label=label, path=path)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Release host-owned load work and runtime when the window closes."""
        super().closeEvent(event)
        if not event.isAccepted() or self._execution_closed:
            return
        self._execution_closed = True
        self.workspace.close()
        self._execution_runtime.shutdown(wait=False)

    def _build_layout(self) -> None:
        """Compose the recognizable hideable catalog-and-canvas splitter."""
        catalog_container = QWidget()
        catalog_layout = QVBoxLayout(catalog_container)
        catalog_layout.setContentsMargins(0, 0, 0, 0)
        catalog_layout.addWidget(self.catalog_panel)
        self._catalog_container = catalog_container
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("viewerSplitter")
        splitter.addWidget(catalog_container)
        splitter.addWidget(self.pane)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 1000])
        self._splitter = splitter
        self.setCentralWidget(splitter)
        self.pane.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def _apply_window_icon(self) -> None:
        """Use the repository logo when the optional asset is present."""
        path = (
            Path(__file__).resolve().parents[2] / "assets" / "logos" / "icon-white.png"
        )
        if path.is_file():
            self.setWindowIcon(QIcon(str(path)))
