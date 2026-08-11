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
"""Regression coverage for physical-viewport raster-tile sizing."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot
from qpane import Config
from qpane.rendering.raster_tile_grid import (
    RasterTileGrid,
    resolve_raster_tile_grid,
)
from qpane.rendering.raster_tile_grid_runtime import RasterTileGridRuntime


@pytest.mark.parametrize(
    ("physical_size", "expected"),
    (
        (QSize(1920, 1080), 512),
        (QSize(3840, 2160), 1024),
        (QSize(5120, 2880), 2048),
        (QSize(6720, 3780), 4096),
        (QSize(7680, 4320), 4096),
    ),
)
def test_automatic_grid_tracks_physical_viewport_classes(
    physical_size: QSize,
    expected: int,
) -> None:
    """Automatic sizing should hold a bounded core-tile count across displays."""
    grid = resolve_raster_tile_grid("auto", 8, physical_size)

    assert grid == RasterTileGrid(expected, 8)


def test_strict_grid_preserves_host_tile_size_exactly() -> None:
    """Positive integer tile sizes should bypass every automatic bucket."""
    grid = resolve_raster_tile_grid(1536, 12, QSize(7680, 4320))

    assert grid == RasterTileGrid(1536, 12)


def test_automatic_grid_uses_hysteresis_around_bucket_boundary() -> None:
    """Small viewport noise should not alternate adjacent tile grids."""
    near_boundary = QSize(4100, 2050)

    assert (
        resolve_raster_tile_grid(
            "auto",
            8,
            near_boundary,
            current_tile_size=1024,
        ).tile_size
        == 1024
    )
    assert (
        resolve_raster_tile_grid(
            "auto",
            8,
            QSize(6720, 3780),
            current_tile_size=2048,
        ).tile_size
        == 4096
    )


def test_automatic_grid_respects_small_cache_allocation() -> None:
    """Automatic entries should leave room for a bounded visible working set."""
    grid = resolve_raster_tile_grid(
        "auto",
        8,
        QSize(6720, 3780),
        cache_limit_bytes=64 * 1024 * 1024,
    )

    assert grid.tile_size == 1024
    assert grid.estimated_bytes <= (64 * 1024 * 1024) // 16


@pytest.mark.parametrize(
    ("tile_size", "tile_overlap", "error"),
    (
        (True, 8, TypeError),
        (0, 8, ValueError),
        ("automatic", 8, TypeError),
        ("auto", True, TypeError),
        ("auto", -1, ValueError),
        ("auto", 512, ValueError),
        (256, 256, ValueError),
    ),
)
def test_grid_rejects_ambiguous_or_invalid_settings(
    tile_size: object,
    tile_overlap: object,
    error: type[Exception],
) -> None:
    """Grid settings should never rely on coercion or a non-positive stride."""
    with pytest.raises(error):
        resolve_raster_tile_grid(tile_size, tile_overlap, QSize(1920, 1080))


def test_grid_dimensions_use_overlap_stride() -> None:
    """Grid coverage should retain the established overlapping crop geometry."""
    grid = RasterTileGrid(1024, 8)

    assert grid.stride == 1016
    assert grid.dimensions_for(2040, 2040) == (2, 2)
    assert grid.dimensions_for(0, 100) == (0, 0)


@dataclass
class _GridConsumer:
    """Record complete runtime transitions without a real tile cache."""

    grid: RasterTileGrid
    cache_limit_bytes: int = 1024 * 1024 * 1024
    replacements: list[RasterTileGrid] = field(default_factory=list)
    cache_configs: int = 0

    def replace_grid(self, grid: RasterTileGrid) -> bool:
        """Accept a changed grid and record it."""
        if grid == self.grid:
            return False
        self.grid = grid
        self.replacements.append(grid)
        return True

    def apply_cache_config(self, config: Config) -> None:
        """Record cache-policy propagation."""
        del config
        self.cache_configs += 1


def test_runtime_debounces_resize_storm_to_latest_bucket(
    qapp: QApplication,
    qtbot: QtBot,
) -> None:
    """A resize storm should invalidate once for its final physical viewport."""
    del qapp
    consumer = _GridConsumer(RasterTileGrid(512, 8))
    changes: list[RasterTileGrid] = []
    runtime = RasterTileGridRuntime(
        config=Config(tile_size="auto"),
        initial_physical_size=QSize(1920, 1080),
        consumer=consumer,
        changed=lambda: changes.append(consumer.grid),
        parent=None,
    )
    try:
        runtime.observe_viewport(QSize(3840, 2160))
        runtime.observe_viewport(QSize(4000, 2200))
        runtime.observe_viewport(QSize(6720, 3780))

        assert runtime.pending
        assert consumer.replacements == []

        qtbot.waitUntil(lambda: not runtime.pending, timeout=1000)

        assert not runtime.pending
        assert consumer.replacements == [RasterTileGrid(4096, 8)]
        assert changes == consumer.replacements
    finally:
        runtime.shutdown()
        runtime.deleteLater()


def test_runtime_strict_override_is_immediate_and_non_adaptive(
    qapp: QApplication,
    qtbot: QtBot,
) -> None:
    """A host-selected integer should remain exact across viewport changes."""
    del qapp
    consumer = _GridConsumer(RasterTileGrid(512, 8))
    runtime = RasterTileGridRuntime(
        config=Config(tile_size="auto"),
        initial_physical_size=QSize(1920, 1080),
        consumer=consumer,
        changed=lambda: None,
        parent=None,
    )
    try:
        runtime.apply_config(Config(tile_size=1536, tile_overlap=12))
        runtime.observe_viewport(QSize(7680, 4320))
        qtbot.waitUntil(lambda: not runtime.pending, timeout=1000)

        assert consumer.grid == RasterTileGrid(1536, 12)
        assert consumer.replacements == [RasterTileGrid(1536, 12)]
        assert consumer.cache_configs == 1
        assert not runtime.pending
    finally:
        runtime.shutdown()
        runtime.deleteLater()
