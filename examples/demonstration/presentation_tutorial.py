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
"""Teach linked, grid, comparison, and host MIME presentation in one dialog."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import cast

from cutecanvas import (
    CanvasContentReference,
    CanvasInspectionGroup,
    CanvasWorkspace,
    CuteCanvas,
    DragSubject,
    OutboundDragPayload,
    OutboundMimeItem,
    ResponsiveGridPolicy,
)
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from examples.demonstration.projection_tutorial import (
    ProjectionTutorialController,
)


class _ReferenceMimeProvider:
    """Demonstrate immediate custom MIME without assuming host file storage."""

    def materialize(
        self,
        subject: DragSubject,
        complete: Callable[[OutboundDragPayload | None, BaseException | None], None],
    ) -> None:
        """Publish a portable text value and a typed document reference."""
        reference = cast(CanvasContentReference, subject.subject_id)
        encoded = json.dumps(
            {
                "document_id": str(reference.document_id),
                "kind": reference.kind.value,
                "composition_id": (
                    None
                    if reference.composition_id is None
                    else str(reference.composition_id)
                ),
            },
            sort_keys=True,
        ).encode("utf-8")
        complete(
            OutboundDragPayload(
                items=(
                    OutboundMimeItem(
                        "application/x-cutecanvas-reference+json",
                        encoded,
                    ),
                ),
                text=subject.label or "CuteCanvas content",
            ),
            None,
        )


class PresentationTutorialController:
    """Own the demo's focused multi-target inspection window."""

    def __init__(
        self,
        canvas: CuteCanvas,
        parent: QWidget,
        *,
        show_status: Callable[[str], None],
    ) -> None:
        """Bind one editor document without copying its composition state."""
        self._canvas = canvas
        self._parent = parent
        self._show_status = show_status
        self._dialog: QDialog | None = None
        self._workspace: CanvasWorkspace | None = None
        self._mode: QComboBox | None = None
        self._projection = ProjectionTutorialController(
            canvas,
            parent,
            show_status=show_status,
        )
        canvas.compositionChanged.connect(lambda _snapshot: self.refresh())

    def show(self) -> None:
        """Open or focus the inspection window when content is available."""
        if not self._canvas.compositionIDs():
            self._show_status("Add a composition before opening multi-view inspection.")
            return
        if self._dialog is None:
            self._build()
        self.refresh()
        assert self._dialog is not None
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()

    def refresh(self) -> None:
        """Reconcile visible targets after document additions or removals."""
        if self._workspace is None or self._mode is None:
            return
        identifiers = tuple(self._canvas.compositionIDs())
        if not identifiers:
            if self._dialog is not None:
                self._dialog.close()
            return
        self._apply_mode(self._mode.currentIndex())

    def close(self) -> None:
        """Close the tutorial window during application teardown."""
        if self._dialog is not None:
            self._dialog.close()

    def _build(self) -> None:
        """Create a restrained document-inspection surface."""
        dialog = QDialog(self._parent)
        dialog.setWindowTitle("Multi-view Inspection")
        dialog.setWindowFlag(Qt.WindowType.Window)
        dialog.resize(1000, 720)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.addWidget(QLabel("Layout", dialog))
        mode = QComboBox(dialog)
        mode.addItems(("Single", "Linked tabs", "Responsive grid", "Comparison"))
        mode.currentIndexChanged.connect(self._apply_mode)
        controls.addWidget(mode)
        export_button = QPushButton("Export Preview…", dialog)
        controls.addWidget(export_button)
        controls.addStretch(1)
        hint = QLabel("Drag from a canvas to try the host MIME provider.", dialog)
        hint.setStyleSheet("color: palette(mid);")
        controls.addWidget(hint)
        layout.addLayout(controls)

        workspace = CanvasWorkspace(
            document_runtime=self._canvas.documentRuntime(),
            features=self._canvas.installedFeatures,
            parent=dialog,
        )
        workspace.setOutboundMimeProvider(_ReferenceMimeProvider())
        export_button.clicked.connect(
            lambda: self._projection.export_active(
                self._active_workspace_canvas(workspace)
            )
        )
        layout.addWidget(workspace, 1)
        self._dialog = dialog
        self._workspace = workspace
        self._mode = mode

    @staticmethod
    def _active_workspace_canvas(workspace: CanvasWorkspace) -> CuteCanvas | None:
        """Return the active document target without exposing a native renderer."""

        active_id = workspace.session.active_composition_id
        return None if active_id is None else workspace.canvasFor(active_id)

    def _apply_mode(self, index: int) -> None:
        """Apply one public workspace presentation from current document IDs."""
        workspace = self._workspace
        if workspace is None:
            return
        identifiers = tuple(self._canvas.compositionIDs())
        if not identifiers:
            return
        active = self._canvas.currentCompositionID()
        primary = active if active in identifiers else identifiers[0]
        ordered = (primary,) + tuple(value for value in identifiers if value != primary)
        if index == 0:
            workspace.setSinglePresentation(primary)
            label = "single composition"
        elif index == 1:
            workspace.setInspectionGroups(
                (CanvasInspectionGroup(uuid.uuid4(), ordered),)
            )
            workspace.setTabbedPresentation(ordered)
            label = "linked native-size tabs"
        elif index == 2:
            workspace.setGridPresentation(
                ordered,
                policy=ResponsiveGridPolicy(),
            )
            label = "responsive composition grid"
        elif len(ordered) >= 2:
            workspace.setComparisonPresentation(ordered[0], ordered[1])
            label = "independent-target comparison"
        else:
            workspace.setSinglePresentation(primary)
            label = "single composition (add another to compare)"
        self._show_status(f"Showing {label}.")
