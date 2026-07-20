#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Contextual modal layer properties for the demonstration host."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QVBoxLayout,
    QWidget,
)

from qpane import QPane

from .layer_inspector import RasterStorageProperties
from .placed_asset_controls import PlacedAssetControls
from .transform_controls import LayerTransformControls


class LayerPropertiesDialog(QDialog):
    """Compose focused property owners for one tree-selected layer."""

    def __init__(
        self,
        qpane: QPane,
        scene_id: uuid.UUID,
        layer_id: uuid.UUID,
        parent: QWidget | None = None,
        *,
        show_status: Callable[[str], None] | None = None,
    ) -> None:
        """Build a modal whose controls use only QPane's public API."""
        super().__init__(parent)
        self.setWindowTitle("Layer Properties")
        self.setModal(True)
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        self.transform = LayerTransformControls(qpane, scene_id, layer_id, self)
        layout.addWidget(self.transform)
        self.placed_asset = PlacedAssetControls(
            qpane,
            self,
            show_status=show_status,
        )
        self.placed_asset.set_target(scene_id, layer_id)
        layout.addWidget(self.placed_asset)
        self.raster_storage = RasterStorageProperties(
            qpane,
            scene_id,
            layer_id,
            self,
            show_status=show_status,
        )
        layout.addWidget(self.raster_storage)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
