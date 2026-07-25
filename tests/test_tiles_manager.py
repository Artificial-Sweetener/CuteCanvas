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

"""Behavior tests for tile execution, sharing, retry, and cancellation."""

from __future__ import annotations

import time
import uuid
from dataclasses import replace

from PySide6.QtGui import QImage, Qt
from qpane.rendering import TileManager

from tests.helpers.config import fixed_cache_config
from tests.helpers.execution_backend import ControlledExecution
from tests.helpers.render_plan import make_tile_key


def _image() -> QImage:
    """Return an opaque source image larger than one configured tile."""
    image = QImage(512, 512, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.white)
    return image


def _manager(execution: ControlledExecution) -> TileManager:
    """Return a tile manager bound to controlled public execution."""
    return TileManager(
        config=fixed_cache_config(),
        execution_scope=execution.scope,
    )


def test_visible_tile_generation_adopts_and_caches(qapp) -> None:
    """One visible request should publish an exact cached tile."""
    execution = ControlledExecution()
    manager = _manager(execution)
    key = make_tile_key()
    ready = []
    manager.tileReady.connect(ready.append)

    assert manager.get_tile(key, _image()) is None
    assert [job.operation for job in execution.pending_jobs()] == [
        "render.tile.visible"
    ]
    execution.run_all()
    qapp.processEvents()

    tile = manager.get_tile(key, _image())
    assert tile is not None and not tile.isNull()
    assert ready == [key]


def test_scene_layers_share_one_source_tile_product(qapp) -> None:
    """Layer instances of one source must not duplicate tile work or storage."""
    execution = ControlledExecution()
    manager = _manager(execution)
    first = make_tile_key()
    second_asset = replace(
        first.asset_key,
        scene_id=uuid.uuid4(),
        layer_id=uuid.uuid4(),
    )
    second = replace(first, asset_key=second_asset)

    assert manager.get_tile(first, _image()) is None
    assert manager.get_tile(second, _image()) is None
    assert len(execution.pending_jobs()) == 1
    execution.run_all()
    qapp.processEvents()

    assert manager.get_tile(first, _image()) is not None
    assert manager.get_tile(second, _image()) is not None
    assert len(manager._tile_cache) == 1


def test_clear_caches_cancels_pending_tile_and_prevents_adoption(qapp) -> None:
    """Clearing a manager should settle pending work before it can publish."""
    execution = ControlledExecution()
    manager = _manager(execution)
    key = make_tile_key()
    manager.get_tile(key, _image())

    manager.clear_caches()
    qapp.processEvents()

    assert not execution.pending_jobs()
    assert execution.cancelled
    assert not manager._tile_cache


def test_prefetch_uses_opportunistic_operation_and_metrics(qapp) -> None:
    """Prefetch should remain distinguishable while sharing tile generation."""
    execution = ControlledExecution()
    manager = _manager(execution)
    key = make_tile_key()

    manager.get_tile(key, _image(), prefetch=True)

    assert [job.operation for job in execution.pending_jobs()] == [
        "render.tile.prefetch"
    ]
    execution.run_all()
    qapp.processEvents()
    metrics = manager.snapshot_metrics()
    assert metrics.prefetch_requested == 1
    assert metrics.prefetch_completed == 1


def test_structured_rejection_retries_visible_tile(qapp) -> None:
    """Saturation should schedule one bounded visible-tile retry."""
    execution = ControlledExecution(rejection_counts={"render.tile.visible": 1})
    manager = _manager(execution)
    key = make_tile_key()
    throttled: list[int] = []
    manager.tilesThrottled.connect(lambda _key, attempt: throttled.append(attempt))

    assert manager.get_tile(key, _image()) is None
    deadline = time.monotonic() + 2.0
    while not execution.pending_jobs() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.002)
    assert throttled == [1]
    execution.run_all()
    qapp.processEvents()
    assert manager.get_tile(key, _image()) is not None


def test_revision_change_never_reuses_stale_tile(qapp) -> None:
    """Tile identity must include source revision across out-of-order adoption."""
    execution = ControlledExecution()
    manager = _manager(execution)
    source_id = uuid.uuid4()
    old_key = make_tile_key(source_id, revision=1)
    new_key = make_tile_key(source_id, revision=2)
    manager.get_tile(old_key, _image())
    manager.get_tile(new_key, _image())
    jobs = execution.pending_jobs()

    execution.run_job(jobs[1])
    execution.run_job(jobs[0])
    qapp.processEvents()

    assert manager.get_tile(old_key, _image()) is not None
    assert manager.get_tile(new_key, _image()) is not None
    assert len(manager._tile_cache) == 2
