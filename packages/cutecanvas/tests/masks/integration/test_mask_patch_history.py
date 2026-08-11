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
"""Prove mask patch history across compact raster storage topology."""

from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np
from cutecanvas import CuteCanvas
from cutecanvas.masks.mask import MaskAssetStore
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from qpane.sdk.scene import RasterBounds


def test_document_undo_restores_patch_after_content_tight_storage_compaction(
    qpane_with_mask: tuple[CuteCanvas, MaskAssetStore, uuid.UUID],
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    """Restore erased edge pixels after archive restore and later compaction."""
    canvas, assets, _composition_id = qpane_with_mask
    mask_id = canvas.createBlankMask(QSize(8, 8), undoable=False)
    assert mask_id is not None
    assert canvas.setActiveMaskID(mask_id)
    layer = assets.get_layer(mask_id)
    assert layer is not None

    restored_pixels = QImage(8, 8, QImage.Format_Grayscale8)
    restored_pixels.fill(0)
    restored_pixels.setPixel(1, 1, 255)
    restored_pixels.setPixel(6, 1, 255)
    layer.coverage.replace_raster_qimage(restored_pixels)
    archive = tmp_path / "restored-mask.ccanvas"
    handles = canvas.editor.persistence.save_document(archive)

    restored = CuteCanvas(features=("mask",))
    try:
        restored_handles = restored.editor.persistence.load_document(
            archive,
            open_first=True,
        )
        assert tuple(handle.id for handle in restored_handles) == tuple(
            handle.id for handle in handles
        )
        restored_assets = restored.document().masks
        restored_layer = restored_assets.get_layer(mask_id)
        assert restored_layer is not None
        assert restored_layer.coverage.raster.bounds == RasterBounds(1, 1, 6, 1)
        assert restored.setActiveMaskID(mask_id)

        edits = restored.mask_service.controller.edits
        assert edits.begin_stroke()
        storage = restored_layer.coverage.raster.storage_rect(RasterBounds(6, 1, 1, 1))
        assert storage is not None
        edits.record_stroke_patch_from_arrays(
            mask_id,
            storage.to_qrect(),
            np.full((1, 1), 255, dtype=np.uint8),
            np.zeros((1, 1), dtype=np.uint8),
        )
        assert edits.commit_stroke(mask_id)
        assert restored_layer.coverage.coverage_value(6, 1) == 0
        assert restored_layer.coverage.compact_raster_storage()
        assert restored_layer.coverage.raster.bounds == RasterBounds(
            1,
            1,
            1,
            1,
        )

        assert restored.undoSceneEdit()
        assert restored_layer.coverage.coverage_value(6, 1) == 255

        assert restored.redoSceneEdit()
        assert restored_layer.coverage.coverage_value(6, 1) == 0
        assert restored_layer.coverage.compact_raster_storage()
        assert restored.undoSceneEdit()
        assert restored_layer.coverage.coverage_value(6, 1) == 255
    finally:
        restored.deleteLater()
        qapp.processEvents()
