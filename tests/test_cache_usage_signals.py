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

"""Signal-based cache usage tracking for managers and consumers."""

from __future__ import annotations

import uuid

import pytest
from PySide6.QtGui import QImage
from qpane.cache.consumers import TileCacheConsumer
from qpane.cache.coordinator import CacheCoordinator
from qpane.rendering.pyramid import PyramidManager
from qpane.rendering.tiles import Tile, TileManager

from tests.helpers.config import fixed_cache_config
from tests.helpers.execution_backend import ControlledExecution
from tests.helpers.render_plan import make_tile_key


@pytest.fixture()
def small_image() -> QImage:
    """Return a tiny ARGB image for cache accounting tests."""
    return QImage(4, 4, QImage.Format_ARGB32)


def _make_tile(image: QImage) -> Tile:
    key = make_tile_key(uuid.uuid4(), None, 1.0, 0, 0)
    return Tile(key=key, image=image)


def test_tile_manager_emits_usage_changed(qapp, small_image: QImage) -> None:
    execution = ControlledExecution()
    manager = TileManager(config=fixed_cache_config(), execution_scope=execution.scope)
    usages: list[int] = []
    manager.usageChanged.connect(usages.append)

    tile = _make_tile(small_image)
    manager.add_tile(tile)
    manager.clear_caches()

    assert usages[0] == tile.size_bytes
    assert usages[-1] == 0


def test_tile_manager_emits_cache_limit_changed(qapp) -> None:
    execution = ControlledExecution()
    manager = TileManager(config=fixed_cache_config(), execution_scope=execution.scope)
    limits: list[int] = []
    manager.cacheLimitChanged.connect(limits.append)

    manager.cache_limit_bytes = 1024

    assert 1024 in limits


def test_pyramid_manager_emits_usage_and_budget(qapp) -> None:
    execution = ControlledExecution()
    manager = PyramidManager(
        config=fixed_cache_config(), execution_scope=execution.scope
    )
    usages: list[int] = []
    limits: list[int] = []
    manager.usageChanged.connect(usages.append)
    manager.cacheLimitChanged.connect(limits.append)

    manager._set_cache_usage_bytes(2048)
    manager.cache_limit_bytes = 4096
    manager._set_cache_usage_bytes(0)

    assert usages == [2048, 0]
    assert 4096 in limits


def test_tile_consumer_updates_coordinator_via_signals(
    qapp, small_image: QImage
) -> None:
    execution = ControlledExecution()
    manager = TileManager(config=fixed_cache_config(), execution_scope=execution.scope)
    coordinator = CacheCoordinator(active_budget_bytes=16_384)
    TileCacheConsumer(manager, coordinator)

    tile = _make_tile(small_image)
    manager.add_tile(tile)

    snapshot = coordinator.snapshot()
    consumer = snapshot["consumers"]["tiles"]
    assert consumer["usage_bytes"] == manager.cache_usage_bytes

    manager.cache_limit_bytes = tile.size_bytes * 2
    snapshot = coordinator.snapshot()
    assert (
        snapshot["consumers"]["tiles"]["preferred_bytes"] == manager.cache_limit_bytes
    )
