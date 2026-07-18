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

"""Integration tests for mask features within the qpane."""

import uuid

from PySide6.QtCore import QRect

from qpane import Config
from qpane.core.config_features import MaskConfigSlice
from qpane.masks.mask import MaskManager
from qpane.masks.mask_controller import MaskController


def test_mask_updated_accepts_uuid(qapp):
    controller = MaskController(
        MaskManager(),
        lambda pt: pt,
        Config(),
        mask_config=MaskConfigSlice(),
    )
    received = []
    controller.mask_updated.connect(
        lambda mask_id, rect: received.append((mask_id, rect))
    )
    mask_id = uuid.uuid4()
    controller.mask_updated.emit(mask_id, QRect())
    assert received and received[0][0] == mask_id
