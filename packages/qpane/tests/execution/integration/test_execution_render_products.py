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

"""Exercise scoped tile and pyramid work through public host backends."""

from __future__ import annotations

import uuid

from PySide6.QtGui import QColor, QImage
from qpane import Config
from qpane.rendering import PyramidManager, PyramidStatus, TileManager
from qpane.rendering.raster_tile_grid import RasterTileGrid
from qpane.scene.identity import (
    SceneLayerAssetKey,
    SceneLayerTileKey,
    SourceRenderAssetKey,
)
from qpane.sdk.execution import ExecutionRuntime
from qpane_test_support.execution_backend import ControllableExecutionBackend

_DETERMINISTIC_CACHE = {"mode": "hard", "budget_mb": 64}


def _source_key() -> SourceRenderAssetKey:
    """Create one source identity for render-product tests."""
    return SourceRenderAssetKey(
        source_id=uuid.uuid4(),
        source_kind="test-raster",
        source_revision=1,
        source_path=None,
    )


def _tile_key(source: SourceRenderAssetKey) -> SceneLayerTileKey:
    """Create one layer-aware key over ``source``."""
    return SceneLayerTileKey(
        asset_key=SceneLayerAssetKey(
            scene_id=uuid.uuid4(),
            layer_id=uuid.uuid4(),
            source_id=source.source_id,
            source_kind=source.source_kind,
            source_revision=source.source_revision,
            source_path=source.source_path,
        ),
        pyramid_asset_key=source,
        pyramid_scale=1.0,
        tile_size=1024,
        tile_overlap=8,
        row=0,
        col=0,
    )


def _image(side: int = 128) -> QImage:
    """Return a non-null detached image."""
    image = QImage(side, side, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor("royalblue"))
    return image


def test_tile_generation_adopts_once_and_cancels_on_shutdown(qapp) -> None:
    """Cache completed pixels and terminalize pending work on manager shutdown."""
    backend = ControllableExecutionBackend()
    runtime = ExecutionRuntime(backend)
    scope = runtime.open_scope(owner_id="tile-test")
    manager = TileManager(
        Config(cache=_DETERMINISTIC_CACHE),
        grid=RasterTileGrid(1024, 8),
        execution_scope=scope,
    )
    source = _source_key()
    first = _tile_key(source)

    assert manager.get_tile(first, _image()) is None
    assert backend.pending_count == 1
    backend.run_next()
    assert manager.get_tile(first, _image()) is not None

    second = SceneLayerTileKey(
        asset_key=first.asset_key,
        pyramid_asset_key=source,
        pyramid_scale=1.0,
        tile_size=first.tile_size,
        tile_overlap=first.tile_overlap,
        row=0,
        col=1,
    )
    assert manager.get_tile(second, _image(256)) is None
    manager.shutdown(wait=False)
    assert backend.pending_count == 0
    assert backend.cancelled


def test_pyramid_generation_adopts_detached_product(qapp) -> None:
    """Keep worker mutation out of manager state until owner adoption."""
    backend = ControllableExecutionBackend()
    runtime = ExecutionRuntime(backend)
    scope = runtime.open_scope(owner_id="pyramid-test")
    manager = PyramidManager(
        Config(min_view_size_px=16, cache=_DETERMINISTIC_CACHE),
        execution_scope=scope,
    )
    source = _source_key()
    manager.generate_pyramid_for_asset(source, _image(128))
    pending = manager.pyramid_for_asset(source)
    assert pending is not None
    assert pending.status == PyramidStatus.GENERATING

    backend.run_next()
    completed = manager.pyramid_for_asset(source)
    assert completed is not None
    assert completed.status == PyramidStatus.COMPLETE
    assert completed.levels
    assert manager.cache_usage_bytes > 0


def test_pyramid_shutdown_releases_completed_products(qapp) -> None:
    """Release full-resolution images and derived levels when the owner closes."""
    backend = ControllableExecutionBackend()
    runtime = ExecutionRuntime(backend)
    scope = runtime.open_scope(owner_id="pyramid-release-test")
    manager = PyramidManager(
        Config(min_view_size_px=16, cache=_DETERMINISTIC_CACHE),
        execution_scope=scope,
    )
    source = _source_key()
    manager.generate_pyramid_for_asset(source, _image(128))
    backend.run_next()

    assert manager.pyramid_for_asset(source) is not None
    assert tuple(manager.iter_cached_asset_keys()) == (source,)
    assert manager.cache_usage_bytes > 0

    manager.shutdown(wait=False)

    assert manager.pyramid_for_asset(source) is None
    assert tuple(manager.iter_cached_asset_keys()) == ()
    assert manager.cache_usage_bytes == 0
