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
"""Mounted lifecycle coverage for automatic raster-tile sizing."""

from __future__ import annotations

import pytest
from qpane.rendering.raster_tile_grid import RasterTileGrid
from qpane_test_support.qt_events import wait_until

from qpane import Config, QPane


def _active_grid(pane: QPane) -> RasterTileGrid:
    """Return the mounted presenter's accepted raster-tile grid."""
    return pane._rendering.presenter.tile_manager.grid


def test_default_grid_adapts_after_high_resolution_resize(qapp) -> None:
    """A stable physical-4K viewport should switch once to 1024-pixel tiles."""
    pane = QPane()
    try:
        pane.show()
        pane.resize(3840, 2160)
        wait_until(
            qapp,
            lambda: _active_grid(pane) == RasterTileGrid(1024, 8),
            failure_message=(
                "automatic raster tile grid did not adapt to the physical 4K viewport"
            ),
        )

        assert _active_grid(pane) == RasterTileGrid(1024, 8)
    finally:
        pane.close()
        pane.deleteLater()
        qapp.processEvents()


def test_strict_grid_does_not_adapt_after_high_resolution_resize(qapp) -> None:
    """A host-selected integer tile size should remain exact when mounted."""
    pane = QPane(config=Config(tile_size=1536, tile_overlap=12))
    try:
        pane.show()
        pane.resize(3840, 2160)
        qapp.processEvents()

        assert _active_grid(pane) == RasterTileGrid(1536, 12)
    finally:
        pane.close()
        pane.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("invalid_tile_size", (0, -1, True, "1024"))
def test_invalid_live_tile_size_does_not_replace_published_settings(
    qapp,
    invalid_tile_size: object,
) -> None:
    """Live configuration should reject invalid grids before publishing them."""
    pane = QPane(config=Config(tile_size=1536))
    try:
        with pytest.raises((TypeError, ValueError)):
            pane.applySettings(tile_size=invalid_tile_size)

        assert pane.settings.tile_size == 1536
        assert _active_grid(pane) == RasterTileGrid(1536, 8)
    finally:
        pane.close()
        pane.deleteLater()
        qapp.processEvents()
