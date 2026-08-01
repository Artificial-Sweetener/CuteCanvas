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
"""Protect host-established mask structure from chronological undo."""

from __future__ import annotations

from pathlib import Path

from cutecanvas import CuteCanvas
from PySide6.QtCore import QRectF, QSize, QTemporaryDir
from PySide6.QtGui import QImage


def test_host_mask_survives_exhaustive_edit_undo(qapp) -> None:
    """Undo may exhaust user edits without removing a host-required mask."""

    del qapp
    canvas = CuteCanvas(features=("mask",))
    try:
        composition = canvas.editor.compositions.create(
            QRectF(0.0, 0.0, 512.0, 512.0),
            title="Host mask",
        )
        mask_id = canvas.createBlankMask(QSize(512, 512), undoable=False)

        assert mask_id is not None
        assert canvas.setActiveMaskID(mask_id)
        assert canvas.editor.history.can_undo is False
        for index in range(64):
            offset = float(index % 16 * 16)
            assert (
                canvas.editor.coverage.rectangle(QRectF(offset, offset, 96.0, 96.0))
                is not None
            )

        for _ in range(64):
            assert canvas.editor.history.undo()
        for _ in range(8):
            assert canvas.editor.history.undo() is False

        assert canvas.editor.history.can_undo is False
        assert canvas.activeMaskID() == mask_id
        assert canvas.maskIDsForComposition(composition.id) == [mask_id]
    finally:
        canvas.deleteLater()


def test_imported_host_mask_starts_without_admission_history(qapp) -> None:
    """A host-imported mask should be current document state, not an edit."""

    del qapp
    temporary = QTemporaryDir()
    assert temporary.isValid()
    path = Path(temporary.path()) / "mask.png"
    image = QImage(64, 48, QImage.Format.Format_Grayscale8)
    image.fill(255)
    assert image.save(str(path))
    canvas = CuteCanvas(features=("mask",))
    try:
        composition = canvas.editor.compositions.create(
            QRectF(0.0, 0.0, 64.0, 48.0),
            title="Imported host mask",
        )

        mask_id = canvas.loadMaskFromFile(str(path), undoable=False)

        assert mask_id is not None
        assert canvas.editor.history.can_undo is False
        assert canvas.maskIDsForComposition(composition.id) == [mask_id]
    finally:
        canvas.deleteLater()


def test_interactive_mask_creation_remains_undoable_by_default(qapp) -> None:
    """Editor-created masks should retain the existing undoable default."""

    del qapp
    canvas = CuteCanvas(features=("mask",))
    try:
        composition = canvas.editor.compositions.create(
            QRectF(0.0, 0.0, 64.0, 48.0),
            title="Interactive mask",
        )
        mask_id = canvas.createBlankMask(QSize(64, 48))

        assert mask_id is not None
        assert canvas.editor.history.can_undo
        assert canvas.editor.history.undo()
        assert canvas.maskIDsForComposition(composition.id) == []
    finally:
        canvas.deleteLater()
