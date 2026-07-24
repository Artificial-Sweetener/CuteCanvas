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
"""Teach asynchronous visible-composition export through stable references."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path

from cutecanvas import CanvasProjectionResult, CuteCanvas
from PySide6.QtWidgets import QFileDialog, QWidget


class ProjectionTutorialController:
    """Own demo export requests without mixing storage into canvas content."""

    def __init__(
        self,
        canvas: CuteCanvas,
        parent: QWidget,
        *,
        show_status: Callable[[str], None],
    ) -> None:
        """Bind the mounted renderer and host-owned status presentation."""
        self._canvas = canvas
        self._parent = parent
        self._show_status = show_status
        self._destinations: dict[uuid.UUID, Path] = {}
        self._connected_canvases: set[int] = {id(canvas)}
        canvas.projectionCompleted.connect(self._projection_finished)

    def export_active(self, canvas: CuteCanvas | None = None) -> None:
        """Choose a PNG path and project the active composition asynchronously."""
        target = self._canvas if canvas is None else canvas
        if id(target) not in self._connected_canvases:
            target.projectionCompleted.connect(self._projection_finished)
            self._connected_canvases.add(id(target))
        composition_id = target.currentCompositionID()
        if composition_id is None:
            self._show_status("Open a composition before exporting a preview.")
            return
        file_path, _selected_filter = QFileDialog.getSaveFileName(
            self._parent,
            "Export Visible Composition",
            "composition.png",
            "PNG images (*.png)",
        )
        if not file_path:
            return
        destination = Path(file_path)
        if not destination.suffix:
            destination = destination.with_suffix(".png")
        reference = target.document().content_reference(composition_id)
        handle = target.requestProjection(reference)
        self._destinations[handle.request_id] = destination
        self._show_status(f"Rendering {destination.name}…")

    def _projection_finished(self, result: CanvasProjectionResult) -> None:
        """Save one current result or report its exact terminal outcome."""
        destination = self._destinations.pop(result.request_id, None)
        if destination is None:
            return
        if result.succeeded and result.image is not None:
            if result.image.save(str(destination), "PNG"):
                self._show_status(f"Exported {destination.name}.")
            else:
                self._show_status(f"Could not write {destination.name}.")
            return
        message = result.message or result.status.value
        self._show_status(f"Preview export did not finish: {message}.")
