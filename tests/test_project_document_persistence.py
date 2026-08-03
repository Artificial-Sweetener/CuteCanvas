#    QPane + CuteCanvas - High-performance PySide6 rendering and editing
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
"""Transitive project-resource persistence through the public editor facade."""

from __future__ import annotations

import json
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest
from cutecanvas import CuteCanvas
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage

from .harness.timing import completion_clock
from .helpers.config import fixed_cache_config


def _image(color: str, width: int = 64, height: int = 48) -> QImage:
    """Return one opaque test raster."""
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(color))
    return image


def _wait_for_color(qapp, canvas: CuteCanvas, expected: QColor) -> None:
    """Wait for asynchronous nested sampling to present the expected center."""
    deadline = completion_clock() + 3.0
    while completion_clock() < deadline:
        qapp.processEvents()
        if canvas.grab().toImage().pixelColor(canvas.rect().center()) == expected:
            return
        time.sleep(0.005)
    raise AssertionError("nested document pixels were not presented")


@pytest.mark.interactive_performance
def test_nested_document_archive_restores_complete_live_resource_graph(
    qapp,
    tmp_path,
) -> None:
    """Saving a root must preserve nested documents and shared child resources."""
    source = CuteCanvas(config=fixed_cache_config(), features=())
    restored = CuteCanvas(config=fixed_cache_config(), features=())
    try:
        child_id = source.createCompositionFromImage(
            _image("red"),
            title="Reusable child",
            label="Pixels",
        )
        root_id = source.createComposition(
            QRectF(0.0, 0.0, 64.0, 48.0),
            title="Root",
        )
        first_layer = source.placeComposition(child_id)
        assert first_layer is not None
        second_layer = source.duplicateLayer(root_id, first_layer)
        assert second_layer is not None
        archive_path = tmp_path / "nested.cutecanvas"

        root = source.editor.compositions.get(root_id)
        assert root is not None
        source.editor.persistence.save(root, archive_path)

        restored.resize(320, 240)
        restored.show()
        loaded = restored.editor.persistence.load(archive_path)
        assert loaded.id == root_id
        assert {document.id for document in restored.editor.compositions} == {
            root_id,
            child_id,
        }
        assert [layer.state.source_id for layer in loaded.layers] == [
            child_id,
            child_id,
        ]
        _wait_for_color(qapp, restored, QColor("red"))
    finally:
        source.close()
        restored.close()
        source.deleteLater()
        restored.deleteLater()
        qapp.processEvents()


def test_invalid_nested_archive_is_rejected_without_mutating_open_project(
    qapp,
    tmp_path,
) -> None:
    """A malformed root identity must fail before any document is installed."""
    source = CuteCanvas(features=())
    target = CuteCanvas(features=())
    try:
        document_id = source.createCompositionFromImage(
            _image("blue"),
            title="Source",
        )
        archive_path = tmp_path / "valid.cutecanvas"
        corrupt_path = tmp_path / "corrupt.cutecanvas"
        document = source.editor.compositions.get(document_id)
        assert document is not None
        source.editor.persistence.save(document, archive_path)
        with zipfile.ZipFile(archive_path, "r") as source_archive:
            entries = {
                name: source_archive.read(name) for name in source_archive.namelist()
            }
        manifest = json.loads(entries["manifest.json"])
        manifest["root_document_id"] = "00000000-0000-0000-0000-000000000000"
        entries["manifest.json"] = json.dumps(manifest).encode("utf-8")
        with zipfile.ZipFile(
            corrupt_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as corrupt_archive:
            for name, payload in entries.items():
                corrupt_archive.writestr(name, payload)

        existing_id = target.createCompositionFromImage(
            _image("green"),
            title="Existing",
        )
        before = target.getCompositionSnapshot()
        with pytest.raises(ValueError, match="root document"):
            target.editor.persistence.load(corrupt_path)
        after = target.getCompositionSnapshot()
        assert after.order == before.order == (existing_id,)
        assert after.current_composition_id == existing_id
    finally:
        source.close()
        target.close()
        source.deleteLater()
        target.deleteLater()
        qapp.processEvents()


def test_complete_document_archive_round_trips_independent_roots(
    qapp,
    tmp_path,
) -> None:
    """Independent roots and mask resources survive one transactional archive."""
    source = CuteCanvas(features=("mask",))
    restored = CuteCanvas(features=("mask",))
    try:
        first_id = source.createCompositionFromImage(_image("red"), title="First")
        mask_id = source.createBlankMask(
            QImage(64, 48, QImage.Format_Grayscale8).size()
        )
        assert mask_id is not None
        coverage = QImage(64, 48, QImage.Format.Format_Grayscale8)
        coverage.fill(255)
        assert source.document().masks.commit_mask_image(mask_id, coverage)
        second_id = source.createCompositionFromImage(_image("blue"), title="Second")
        path = tmp_path / "complete.cutecanvas"

        saved = source.editor.persistence.save_document(path)
        assert tuple(handle.id for handle in saved) == (first_id, second_id)
        loaded = restored.editor.persistence.load_document(path, open_first=False)

        assert tuple(handle.id for handle in loaded) == (first_id, second_id)
        assert restored.currentCompositionID() is None
        assert restored.document().masks.get_layer(mask_id) is not None
    finally:
        source.close()
        restored.close()
        source.deleteLater()
        restored.deleteLater()
        qapp.processEvents()


def test_document_snapshot_is_detached_for_background_persistence(
    qapp,
    tmp_path,
) -> None:
    """Write a stable public snapshot after the live document changes again."""
    source = CuteCanvas(features=("mask",))
    restored = CuteCanvas(features=("mask",))
    try:
        composition_id = source.createCompositionFromImage(_image("red"))
        mask_id = source.createBlankMask(
            QImage(64, 48, QImage.Format_Grayscale8).size()
        )
        assert mask_id is not None
        snapshot = source.editor.persistence.capture_document()

        changed = QImage(64, 48, QImage.Format_Grayscale8)
        changed.fill(255)
        assert source.document().masks.commit_mask_image(mask_id, changed)
        path = tmp_path / "detached.cutecanvas"
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(
                source.editor.persistence.write_document,
                snapshot,
                path,
            ).result(timeout=5.0)

        loaded = restored.editor.persistence.load_document(path, open_first=False)
        persisted = restored.exportMaskImage(
            mask_id,
            composition_id=composition_id,
        )

        assert tuple(handle.id for handle in loaded) == (composition_id,)
        assert snapshot.composition_ids == (composition_id,)
        assert persisted is not None
        assert persisted.pixelColor(24, 20).value() == 0
    finally:
        source.close()
        restored.close()
        source.deleteLater()
        restored.deleteLater()
        qapp.processEvents()
