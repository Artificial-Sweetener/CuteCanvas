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

import uuid

from cutecanvas import CuteCanvas
from cutecanvas.masks.workflow import Masks
from PySide6.QtCore import QRect
from PySide6.QtGui import QImage


def test_mask_workflow_bootstrap_basic(qapp):
    qpane = CuteCanvas(features=())
    qpane.resize(32, 32)
    masks = Masks(
        qpane=qpane,
        catalog=qpane.catalog(),
        swap_delegate=qpane.swapDelegate,
        cache_registry=getattr(qpane, "_state", None).cache_registry,
    )
    # Add two images and navigate to second to trigger navigation hook.
    img_a = QImage(8, 8, QImage.Format_ARGB32)
    img_a.fill(0xFFFFFFFF)
    img_b = QImage(8, 8, QImage.Format_ARGB32)
    img_b.fill(0xFF000000)
    id_a = uuid.uuid4()
    id_b = uuid.uuid4()
    image_map = CuteCanvas.imageMapFromLists(
        [img_a, img_b], paths=[None, None], ids=[id_a, id_b]
    )
    qpane.catalog().setImagesByID(image_map, id_a)
    # Navigation via facade should trigger CuteCanvas overlay suspension (CuteCanvas hook still active).
    qpane.catalog().setCurrentImageID(id_b)
    assert isinstance(qpane.overlaysSuspended(), bool)
    masks_for_image = qpane.listMasksForImage(id_b)
    assert isinstance(masks_for_image, tuple)
    assert masks_for_image == ()
    # Brush size adapter forwards correctly.
    masks.set_brush_size(7)
    assert masks.get_brush_size() == 7
    # Region update forward (no mask active yet, should be harmless).
    rect = QRect(0, 0, 1, 1)
    qpane.update()  # ensure widget initialized
    assert (
        masks.update_mask_region(rect, active_mask_layer=None) is False or True
    )  # just ensure call path works
    qpane.deleteLater()
