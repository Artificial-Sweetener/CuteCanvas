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

"""Behavior tests for tile execution, sharing, retry, and cancellation."""

from __future__ import annotations

import time
import uuid
from dataclasses import replace

import pytest
from cutecanvas_test_support.config import fixed_cache_config
from cutecanvas_test_support.execution_backend import ControlledExecution
from cutecanvas_test_support.render_plan import make_tile_key
from PySide6.QtGui import QImage, Qt
from qpane.rendering.raster_tile_grid import RasterTileGrid
from qpane.rendering.tiles import Tile

from qpane.rendering import TileManager


def _image() -> QImage:
    """Return an opaque source image larger than one configured tile."""
    image = QImage(512, 512, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.white)
    return image


def _manager(execution: ControlledExecution) -> TileManager:
    """Return a tile manager bound to controlled public execution."""
    return TileManager(
        config=fixed_cache_config(),
        grid=RasterTileGrid(64, 0),
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


def test_rejected_tile_admission_never_announces_an_unavailable_product(qapp) -> None:
    """A generated tile must not trigger redraw loops when it cannot be retained."""
    execution = ControlledExecution()
    manager = _manager(execution)
    manager.cache_limit_bytes = 0
    key = make_tile_key()
    ready: list[object] = []
    manager.tileReady.connect(ready.append)

    assert not manager.can_retain_tile(_image())
    assert manager.get_tile(key, _image()) is None
    execution.run_all()
    qapp.processEvents()

    assert ready == []
    assert manager.cache_usage_bytes == 0
    assert not manager._tile_cache


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


def test_grid_replacement_cancels_work_and_invalidates_cached_tiles(qapp) -> None:
    """A grid transition should retire every product and reject old-grid keys."""
    execution = ControlledExecution()
    manager = _manager(execution)
    old_key = make_tile_key()
    manager.add_tile(Tile(old_key, _image().copy(0, 0, 64, 64)))
    manager.get_tile(replace(old_key, row=1), _image())

    assert manager.cache_usage_bytes > 0
    assert execution.pending_jobs()

    assert manager.replace_grid(RasterTileGrid(128, 8))
    qapp.processEvents()

    assert manager.grid == RasterTileGrid(128, 8)
    assert manager.cache_usage_bytes == 0
    assert not manager._tile_cache
    assert not execution.pending_jobs()
    assert execution.cancelled
    with pytest.raises(ValueError, match="does not match"):
        manager.get_tile(old_key, _image())


def test_retired_grid_result_cannot_publish_after_transition(qapp) -> None:
    """Late executor adoption should not cache or signal a retired tile grid."""
    execution = ControlledExecution()
    manager = _manager(execution)
    old_key = make_tile_key()
    ready: list[object] = []
    manager.tileReady.connect(ready.append)

    manager.replace_grid(RasterTileGrid(128, 8))
    manager._on_tile_generated(Tile(old_key, _image().copy(0, 0, 64, 64)))
    qapp.processEvents()

    assert manager.cache_usage_bytes == 0
    assert not manager._tile_cache
    assert ready == []


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
