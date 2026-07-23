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

"""Ensure CuteCanvas exposes a structured catalog snapshot helper."""

from __future__ import annotations

import uuid
from pathlib import Path

from cutecanvas import CatalogSnapshot, CuteCanvas, LinkedGroup
from PySide6.QtGui import QImage


def _solid_image() -> QImage:
    """Return a tiny ARGB32 image for snapshot tests."""
    image = QImage(8, 8, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    return image


def test_catalog_snapshot_reports_order_and_links(qapp) -> None:
    qpane = CuteCanvas(features=())
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    image_map = CuteCanvas.imageMapFromLists(
        images=[_solid_image(), _solid_image()],
        paths=[Path("first.png"), Path("second.png")],
        ids=[first_id, second_id],
    )
    qpane.setImagesByID(image_map, current_id=first_id)
    group = LinkedGroup(group_id=uuid.uuid4(), members=(first_id, second_id))
    qpane.setLinkedGroups((group,))
    snapshot = qpane.getCatalogSnapshot()
    assert isinstance(snapshot, CatalogSnapshot)
    assert snapshot.order == (first_id, second_id)
    assert snapshot.current_image_id == first_id
    assert snapshot.active_mask_id is None
    assert snapshot.mask_capable is False
    assert snapshot.linked_groups == (group,)
    assert snapshot.catalog[first_id].path == Path("first.png")
    assert snapshot.catalog[second_id].path == Path("second.png")
    qpane.deleteLater()
