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
"""Lifecycle regressions for atomically staged navigation frames."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRect, QSize
from qpane import QtOwnerDispatcher
from qpane.rendering.incremental_frame import IncrementalFrameRefiner
from qpane_test_support.execution_backend import ControlledExecution
from qpane_test_support.render_plan import make_render_plan


def test_cancel_retires_result_already_queued_for_owner_adoption(qapp) -> None:
    """A completed stale worker must not publish after cancellation wins."""
    execution = ControlledExecution()
    owner = QObject()
    dispatcher = QtOwnerDispatcher(owner)
    scope = execution.runtime.open_scope(
        owner_id="incremental-frame-race",
        dispatcher=dispatcher,
    )
    prepared: list[bool] = []
    published: list[object] = []
    refiner = IncrementalFrameRefiner(
        parent=owner,
        execution_scope=scope,
        prepare=lambda: prepared.append(True),
        discard=lambda: None,
        transfer_patch=lambda _image, _rect: None,
        publish=published.append,
        failed=lambda: None,
    )
    plan = make_render_plan(QRect(0, 0, 64, 64))

    assert refiner.begin(
        plan,
        physical_size=QSize(64, 64),
        device_pixel_ratio=1.0,
        overscan_physical_px=0,
    )
    execution.run_operation("render.navigation_frame")
    assert refiner.pending
    refiner.cancel()
    qapp.processEvents()

    assert prepared == []
    assert published == []
    assert not refiner.pending
