#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Contextual public-API controls for placed assets in the demo inspector."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QWidget,
)

from qpane import QPane


class PlacedAssetControls(QGroupBox):
    """Present provenance actions only while a placed layer is selected."""

    def __init__(
        self,
        qpane: QPane,
        parent: QWidget | None = None,
        *,
        show_status: Callable[[str], None] | None = None,
    ) -> None:
        """Build compact contextual controls and subscribe to public signals."""
        super().__init__("Placed Asset", parent)
        self._qpane = qpane
        self._show_status = show_status or _ignore_status
        self._target: tuple[uuid.UUID, uuid.UUID] | None = None
        self._pending_targets: dict[
            uuid.UUID,
            tuple[uuid.UUID, uuid.UUID],
        ] = {}
        layout = QGridLayout(self)
        self._status = QLabel(self)
        self._path = QLabel(self)
        self._path.setWordWrap(True)
        layout.addWidget(self._status, 0, 0, 1, 2)
        layout.addWidget(self._path, 1, 0, 1, 2)
        self._duplicate = QPushButton("Duplicate", self)
        self._refresh = QPushButton("Refresh", self)
        self._relink = QPushButton("Relink…", self)
        self._embed = QPushButton("Embed", self)
        self._rasterize = QPushButton("Rasterize", self)
        layout.addWidget(self._duplicate, 2, 0)
        layout.addWidget(self._refresh, 2, 1)
        layout.addWidget(self._relink, 3, 0)
        layout.addWidget(self._embed, 3, 1)
        layout.addWidget(self._rasterize, 4, 0, 1, 2)
        self._duplicate.clicked.connect(self._duplicate_target)
        self._refresh.clicked.connect(self._refresh_target)
        self._relink.clicked.connect(self._relink_target)
        self._embed.clicked.connect(self._embed_target)
        self._rasterize.clicked.connect(self._rasterize_target)
        self._qpane.placedAssetRequestCompleted.connect(self._request_completed)
        self.setVisible(False)

    def set_target(self, scene_id: uuid.UUID, layer_id: uuid.UUID) -> None:
        """Show current provenance when ``layer_id`` is a placed source."""
        state = self._qpane.placedAssetState(scene_id, layer_id)
        self._target = None if state is None else (scene_id, layer_id)
        self.setVisible(state is not None)
        if state is None:
            return
        pending = self._pending_request_for(self._target)
        status = state.status.title()
        if state.error:
            status = f"{status}: {state.error}"
        self._status.setText(
            "Rasterizing to editable pixels…"
            if pending is not None
            else f"{state.mode.title()} · {status}"
        )
        self._path.setText(
            "Stored in this composition"
            if state.source_path is None
            else str(state.source_path)
        )
        linked = state.mode == "linked"
        ready = pending is None
        self._duplicate.setEnabled(ready)
        self._refresh.setEnabled(ready and linked)
        self._relink.setEnabled(ready and linked)
        self._embed.setEnabled(ready and linked and state.status != "loading")
        self._rasterize.setEnabled(ready)
        self._rasterize.setText("Rasterizing…" if not ready else "Rasterize")

    def clear_target(self) -> None:
        """Hide controls when no placed layer is selected."""
        self._target = None
        self.setVisible(False)

    def _duplicate_target(self) -> None:
        """Duplicate the current instance while sharing its source."""
        if self._target is None:
            return
        layer_id = self._qpane.duplicatePlacedAsset(*self._target)
        if layer_id is not None:
            self._qpane.setSelectedLayer(self._target[0], layer_id)

    def _refresh_target(self) -> None:
        """Request a non-blocking reload from the current linked path."""
        if self._target is not None:
            self._qpane.refreshPlacedAsset(*self._target)

    def _relink_target(self) -> None:
        """Choose a replacement linked source without blocking decode."""
        if self._target is None:
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Relink Placed Asset",
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.gif *.webp)",
        )
        if file_path:
            self._qpane.relinkPlacedAsset(*self._target, Path(file_path))

    def _embed_target(self) -> None:
        """Detach the current source from external provenance."""
        if self._target is not None and self._qpane.embedPlacedAsset(*self._target):
            self.set_target(*self._target)

    def _rasterize_target(self) -> None:
        """Convert the current source to an editable raster at natural size."""
        target = self._target
        if target is None:
            return
        request_id = self._qpane.rasterizePlacedAsset(*target)
        if request_id is None:
            self._show_status("The selected layer could not be rasterized.")
            return
        self._pending_targets[request_id] = target
        self.set_target(*target)
        self._show_status(
            "Rasterizing placed artwork. Pixel editing will be available when it "
            "completes."
        )

    def _request_completed(
        self,
        request_id: uuid.UUID,
        scene_id: object,
        layer_id: object,
        succeeded: bool,
        message: str,
    ) -> None:
        """Refresh only when a request addresses the current target."""
        target = self._pending_targets.pop(request_id, None)
        if target is None or target != (scene_id, layer_id):
            return
        del succeeded, message
        if self._target == target:
            self.set_target(*self._target)

    def _pending_request_for(
        self,
        target: tuple[uuid.UUID, uuid.UUID] | None,
    ) -> uuid.UUID | None:
        """Return the pending rasterization request for ``target`` when present."""
        return next(
            (
                request_id
                for request_id, pending_target in self._pending_targets.items()
                if pending_target == target
            ),
            None,
        )


def _ignore_status(_message: str) -> None:
    """Accept status messages when the embedding host has no status surface."""
