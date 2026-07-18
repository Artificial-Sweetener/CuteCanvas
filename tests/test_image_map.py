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

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from PySide6.QtGui import QImage

from qpane import QPane
from qpane.catalog import ImageMap
from qpane.types import CatalogEntry


def _make_image(seed: int) -> QImage:
    image = QImage(2, 2, QImage.Format_ARGB32)
    image.fill(seed)
    return image


def test_image_map_from_lists_preserves_inputs_and_order() -> None:
    images = [_make_image(idx) for idx in range(3)]
    paths = [Path(f"image_{idx}.png") for idx in range(3)]
    ids = [uuid4() for _ in range(3)]
    result = QPane.imageMapFromLists(images, paths=paths, ids=ids)
    assert list(result.keys()) == ids
    for idx, image_id in enumerate(ids):
        stored_entry = result[image_id]
        assert isinstance(stored_entry, CatalogEntry)
        assert stored_entry.image is images[idx]
        assert stored_entry.path == paths[idx]


def test_image_map_from_lists_generates_ids_when_missing() -> None:
    images = [_make_image(idx) for idx in range(2)]
    result = QPane.imageMapFromLists(images)
    assert len(result) == len(images)
    assert next(iter(result.values())).path is None
    assert all(value.path is None for value in result.values())
    assert all(isinstance(key, UUID) for key in result)


def test_image_map_from_lists_raises_on_path_length_mismatch() -> None:
    images = [_make_image(0), _make_image(1)]
    with pytest.raises(ValueError) as excinfo:
        QPane.imageMapFromLists(images, paths=[Path("one.png")])
    assert str(excinfo.value) == "paths length mismatch: expected 2, received 1"


def test_image_map_from_lists_raises_on_id_length_mismatch() -> None:
    images = [_make_image(0), _make_image(1)]
    with pytest.raises(ValueError) as excinfo:
        QPane.imageMapFromLists(images, ids=[uuid4()])
    assert str(excinfo.value) == "ids length mismatch: expected 2, received 1"


def test_qpane_static_wrapper_delegates_to_helper() -> None:
    images = [_make_image(idx) for idx in range(2)]
    paths = [Path("first.png"), Path("second.png")]
    ids = [uuid4(), uuid4()]
    via_qpane: ImageMap = QPane.imageMapFromLists(images, paths=paths, ids=ids)
    assert list(via_qpane.keys()) == ids
    for image_id in ids:
        entry = via_qpane[image_id]
        index = ids.index(image_id)
        assert entry.image is images[index]
        assert entry.path == paths[index]


def test_qpane_static_wrapper_propagates_validation() -> None:
    images = [_make_image(0), _make_image(1)]
    with pytest.raises(ValueError) as excinfo:
        QPane.imageMapFromLists(images, paths=[Path("only.png")])
    assert str(excinfo.value) == "paths length mismatch: expected 2, received 1"


def test_image_map_rejects_non_image_values() -> None:
    images = [None]
    with pytest.raises(TypeError):
        QPane.imageMapFromLists(images)
