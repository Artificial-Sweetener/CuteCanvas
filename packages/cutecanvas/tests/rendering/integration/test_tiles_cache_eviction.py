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

"""Targeted tests for tile cache admission and eviction helpers."""

from __future__ import annotations

import uuid
from collections import OrderedDict
from pathlib import Path

import pytest
from cutecanvas import Config
from cutecanvas_test_support.execution_backend import ControlledExecution
from cutecanvas_test_support.render_plan import make_tile_key
from qpane.rendering.raster_tile_grid import RasterTileGrid
from qpane.rendering.tiles import TileManager


@pytest.mark.usefixtures("qapp")
def test_allow_cache_insert_honors_guard(caplog):
    """Admission guards should veto inserts and log only once per key."""
    execution = ControlledExecution()
    manager = TileManager(
        config=Config(),
        grid=RasterTileGrid(64, 0),
        execution_scope=execution.scope,
    )
    manager.cache_limit_bytes = 100
    manager.set_admission_guard(lambda _size: False)
    image_id = uuid.uuid4()
    key = make_tile_key(image_id, Path("a.png"), 1.0, 0, 0)
    caplog.set_level("WARNING")
    assert manager._allow_cache_insert(50, key) is False
    assert manager._allow_cache_insert(50, key) is False
    warnings = [
        record
        for record in caplog.records
        if "requested item exceeds budget" in record.message
    ]
    assert len(warnings) == 1


@pytest.mark.usefixtures("qapp")
def test_schedule_cache_eviction_coalesces_owner_callbacks():
    """Repeated eviction scheduling should retain one owner-loop callback."""
    execution = ControlledExecution()
    manager = TileManager(
        config=Config(),
        grid=RasterTileGrid(64, 0),
        execution_scope=execution.scope,
    )
    manager.cache_limit_bytes = 10
    manager._cache_size_bytes = 20
    manager._tile_cache = OrderedDict({object(): object()})
    manager._schedule_cache_eviction()
    manager._schedule_cache_eviction()
    assert manager._eviction.pending


@pytest.mark.usefixtures("qapp")
def test_evict_cache_batch_drops_entries():
    """Eviction should remove cached tiles and update bytes."""
    execution = ControlledExecution()
    manager = TileManager(
        config=Config(),
        grid=RasterTileGrid(64, 0),
        execution_scope=execution.scope,
    )
    image_id = uuid.uuid4()
    key = make_tile_key(image_id, Path("a.png"), 1.0, 0, 0)
    manager.cache_limit_bytes = 0
    manager._tile_cache = OrderedDict({key: type("Tile", (), {"size_bytes": 5})()})
    manager._cache_size_bytes = 5
    manager._evict_cache_batch()
    assert manager._cache_size_bytes == 0
    assert not manager._tile_cache
    assert manager._evictions_total == 1
