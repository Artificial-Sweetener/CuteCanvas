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

"""Ensure QPane exposes catalog-backed catalog state via the public API."""

import logging
import uuid

import pytest
from PySide6.QtGui import QImage, Qt

from qpane import Config, QPane


def _cleanup_qpane(qpane, qapp):
    qpane.deleteLater()
    qapp.processEvents()


def _make_image(width: int, height: int, color=Qt.white) -> QImage:
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(color)
    return image


def test_current_image_path_tracks_catalog_selection(qapp, tmp_path):
    qpane = QPane(features=())
    qpane.resize(32, 32)
    try:
        catalog = qpane.catalog()
        first_id = uuid.uuid4()
        second_id = uuid.uuid4()
        first_path = tmp_path / "first.png"
        second_path = tmp_path / "second.png"
        image_map = QPane.imageMapFromLists(
            images=[_make_image(12, 8, Qt.black), _make_image(16, 10, Qt.red)],
            paths=[first_path, second_path],
            ids=[first_id, second_id],
        )
        qpane.setImagesByID(image_map, first_id)
        assert qpane.currentImagePath == first_path
        assert catalog.currentImagePath() == first_path
        qpane.setCurrentImageID(second_id)
        assert qpane.currentImagePath == second_path
        assert catalog.currentImagePath() == second_path
    finally:
        _cleanup_qpane(qpane, qapp)


def test_current_image_path_resets_with_catalog_clear(qapp, tmp_path):
    qpane = QPane(features=())
    qpane.resize(32, 32)
    try:
        catalog = qpane.catalog()
        image_id = uuid.uuid4()
        image_path = tmp_path / "only.png"
        image_map = QPane.imageMapFromLists(
            images=[_make_image(10, 10, Qt.green)],
            paths=[image_path],
            ids=[image_id],
        )
        qpane.setImagesByID(image_map, image_id)
        assert qpane.currentImagePath == image_path
        assert catalog.currentImagePath() == image_path
        qpane.clearImages()
        assert qpane.currentImagePath is None
        assert catalog.currentImagePath() is None
    finally:
        _cleanup_qpane(qpane, qapp)


def test_set_image_updates_catalog_and_path(qapp, tmp_path):
    qpane = QPane(features=())
    qpane.resize(32, 32)
    try:
        catalog = qpane.catalog()
        image_id = uuid.uuid4()
        original_path = tmp_path / "original.png"
        image_map = QPane.imageMapFromLists(
            images=[_make_image(12, 12, Qt.white)],
            paths=[original_path],
            ids=[image_id],
        )
        qpane.setImagesByID(image_map, image_id)
        replacement = _make_image(14, 14, Qt.black)
        # Update using the public API (setImagesByID)
        image_map_update = QPane.imageMapFromLists(
            images=[replacement],
            paths=[original_path],
            ids=[image_id],
        )
        qpane.setImagesByID(image_map_update, image_id)
        assert qpane.currentImagePath == original_path
        assert catalog.currentImagePath() == original_path
        stored = catalog.currentImage()
        assert stored is not None
        assert stored.size() == replacement.size()
        updated_path = tmp_path / "updated.png"
        image_map_path_update = QPane.imageMapFromLists(
            images=[replacement],
            paths=[updated_path],
            ids=[image_id],
        )
        qpane.setImagesByID(image_map_path_update, image_id)
        assert qpane.currentImagePath == updated_path
        assert catalog.currentImagePath() == updated_path
    finally:
        _cleanup_qpane(qpane, qapp)


def test_core_mode_logs_unused_mask_overrides(qapp, caplog):
    caplog.set_level(logging.WARNING)
    config = Config()
    config.mask_border_enabled = True
    qpane = QPane(config=config, features=(), config_strict=False)
    try:
        messages = [
            record.getMessage()
            for record in caplog.records
            if "feature 'mask'" in record.getMessage()
            or "feature 'mask' is inactive" in record.getMessage()
        ]
        assert messages, "expected warning about inactive mask overrides"
        snapshot = qpane.gatherDiagnostics()
        assert any(
            record.label == "Config (mask)" and "ignored" in record.value
            for record in snapshot.records
        )
    finally:
        _cleanup_qpane(qpane, qapp)


def test_strict_mode_blocks_inactive_overrides(qapp):
    config = Config()
    config.mask_border_enabled = True
    with pytest.raises(ValueError):
        QPane(config=config, features=(), config_strict=True)
