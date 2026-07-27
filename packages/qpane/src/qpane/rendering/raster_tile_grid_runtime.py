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
"""Debounced lifecycle for viewport-dependent raster-tile grids."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from PySide6.QtCore import QObject, QSize, QTimer

from ..core import Config
from .raster_tile_grid import (
    AUTO_TILE_SIZE,
    RasterTileGrid,
    resolve_raster_tile_grid,
)

_VIEWPORT_DEBOUNCE_MS = 120


class RasterTileGridConsumer(Protocol):
    """Accept grid and cache-policy transitions from the focused runtime."""

    @property
    def grid(self) -> RasterTileGrid:
        """Return the active grid accepted by tile generation."""
        ...

    @property
    def cache_limit_bytes(self) -> int:
        """Return the active tile-cache allocation."""
        ...

    def replace_grid(self, grid: RasterTileGrid) -> bool:
        """Replace the grid and invalidate incompatible work and products."""
        ...

    def apply_cache_config(self, config: Config) -> None:
        """Refresh cache budgets without interpreting tile-grid policy."""
        ...


class RasterTileGridRuntime(QObject):
    """Own automatic sizing, resize debounce, and complete grid transitions."""

    def __init__(
        self,
        *,
        config: Config,
        initial_physical_size: QSize,
        consumer: RasterTileGridConsumer,
        changed: Callable[[], None],
        parent: QObject | None,
    ) -> None:
        """Bind one tile consumer to viewport-dependent configuration."""
        super().__init__(parent)
        self._consumer = consumer
        self._changed = changed
        self._tile_size_setting: object = config.tile_size
        self._tile_overlap_setting: object = config.tile_overlap
        self._latest_physical_size = QSize(initial_physical_size)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_VIEWPORT_DEBOUNCE_MS)
        self._timer.timeout.connect(self._commit_automatic_grid)

    @property
    def pending(self) -> bool:
        """Return whether a viewport-dependent transition is debouncing."""
        return self._timer.isActive()

    def apply_config(self, config: Config) -> None:
        """Apply strict overrides immediately or reselect the automatic grid."""
        self.validate_config(config)
        previous_setting = self._tile_size_setting
        previous_overlap = self._tile_overlap_setting
        self._consumer.apply_cache_config(config)
        self._tile_size_setting = config.tile_size
        self._tile_overlap_setting = config.tile_overlap
        mode_changed = previous_setting != self._tile_size_setting
        overlap_changed = previous_overlap != self._tile_overlap_setting
        self._timer.stop()
        grid = self._resolve(use_hysteresis=not mode_changed and not overlap_changed)
        self._replace(grid)

    def validate_config(self, config: Config) -> None:
        """Reject tile-grid settings before any rendering state is mutated."""
        resolve_raster_tile_grid(
            config.tile_size,
            config.tile_overlap,
            self._latest_physical_size,
            cache_limit_bytes=self._consumer.cache_limit_bytes,
        )

    def observe_viewport(self, physical_size: QSize) -> None:
        """Debounce one physical resize when automatic sizing is active."""
        self._latest_physical_size = QSize(physical_size)
        if self._tile_size_setting != AUTO_TILE_SIZE:
            self._timer.stop()
            return
        candidate = self._resolve(use_hysteresis=True)
        if candidate == self._consumer.grid:
            self._timer.stop()
            return
        self._timer.start()

    def shutdown(self) -> None:
        """Stop a pending resize transition before owner teardown."""
        self._timer.stop()

    def _commit_automatic_grid(self) -> None:
        """Commit the newest stable viewport bucket after resize settles."""
        if self._tile_size_setting != AUTO_TILE_SIZE:
            return
        self._replace(self._resolve(use_hysteresis=True))

    def _resolve(self, *, use_hysteresis: bool) -> RasterTileGrid:
        """Resolve settings against the latest physical viewport."""
        return resolve_raster_tile_grid(
            self._tile_size_setting,
            self._tile_overlap_setting,
            self._latest_physical_size,
            current_tile_size=(
                self._consumer.grid.tile_size if use_hysteresis else None
            ),
            cache_limit_bytes=self._consumer.cache_limit_bytes,
        )

    def _replace(self, grid: RasterTileGrid) -> None:
        """Publish one complete grid transition and invalidate its frame."""
        if self._consumer.replace_grid(grid):
            self._changed()


__all__ = ["RasterTileGridConsumer", "RasterTileGridRuntime"]
