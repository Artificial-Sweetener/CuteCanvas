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
"""Asynchronous empty-catalog placeholder presentation and interaction policy."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRunnable, QSize, Signal
from PySide6.QtGui import QImage, QImageReader

from ..concurrency import BaseWorker, TaskExecutorProtocol, TaskHandle
from ..core.config import Config, PlaceholderSettings
from ..rendering.sdk import RasterSource, RenderLayer, RenderScene
from ..rendering.viewport import Viewport, ViewportZoomMode
from ..scene.identity import (
    placeholder_layer_id,
    placeholder_scene_id,
    placeholder_source_id,
)
from .viewer_catalog import ViewerCatalog, ViewerCatalogEntry

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ViewerPlaceholderState:
    """Describe the configured and currently presented placeholder."""

    active: bool
    loading: bool
    source_path: Path | None
    error: str | None


class _PlaceholderLoadSignals(QObject):
    """Deliver one background image decode result to the GUI thread."""

    finished = Signal(int, object, object)
    error = Signal(int, object, str)


class _PlaceholderLoadWorker(QRunnable, BaseWorker):
    """Decode one configured placeholder without blocking Qt input."""

    def __init__(self, generation: int, path: Path) -> None:
        """Store immutable request identity and source path."""
        QRunnable.__init__(self)
        BaseWorker.__init__(self, logger=logger)
        self.generation = generation
        self.path = Path(path)
        self.signals = _PlaceholderLoadSignals()

    def run(self) -> None:
        """Decode the image and publish a detached worker result."""
        if self.is_cancelled:
            self.emit_finished(False, (self.generation, self.path, "cancelled"))
            return
        reader = QImageReader(str(self.path))
        reader.setAutoTransform(True)
        image = reader.read()
        if self.is_cancelled:
            self.emit_finished(False, (self.generation, self.path, "cancelled"))
        elif image.isNull():
            self.emit_finished(
                False,
                (self.generation, self.path, reader.errorString()),
            )
        else:
            self.emit_finished(True, (self.generation, self.path, image))


class ViewerPlaceholder(QObject):
    """Own placeholder pixels, stale-safe loading, and temporary viewer policy."""

    changed = Signal(object)
    """Emit ``ViewerPlaceholderState`` after effective lifecycle changes."""

    def __init__(
        self,
        *,
        catalog: ViewerCatalog,
        viewport: Viewport,
        executor: TaskExecutorProtocol,
        set_scene: Callable[[RenderScene | None, bool], None],
        set_navigation_enabled: Callable[[bool], None],
        parent: QObject | None = None,
    ) -> None:
        """Bind placeholder state to catalog emptiness and a scene sink."""
        super().__init__(parent)
        self._catalog = catalog
        self._viewport = viewport
        self._executor = executor
        self._set_scene = set_scene
        self._set_navigation_enabled = set_navigation_enabled
        self._settings = PlaceholderSettings()
        self._image: QImage | None = None
        self._path: Path | None = None
        self._active = False
        self._loading = False
        self._error: str | None = None
        self._generation = 0
        self._worker: _PlaceholderLoadWorker | None = None
        self._handle: TaskHandle | None = None
        self._suspended = False
        catalog.selectionChanged.connect(self._selection_changed)

    def state(self) -> ViewerPlaceholderState:
        """Return immutable placeholder lifecycle state."""
        return ViewerPlaceholderState(
            active=self._active,
            loading=self._loading,
            source_path=self._path,
            error=self._error,
        )

    def apply_config(self, config: Config) -> None:
        """Apply placeholder policy and asynchronously resolve a changed path."""
        settings = config.placeholder.clone()
        source = settings.source
        next_path = None if not source else Path(source)
        self._settings = settings
        self._suspended = False
        if next_path != self._path or (next_path is not None and self._image is None):
            self._begin_load(next_path)
            return
        if self._catalog.current is None:
            self._present_or_blank()

    def set_image(
        self,
        image: QImage | None,
        *,
        path: Path | None = None,
    ) -> None:
        """Install an already-decoded placeholder without scheduling I/O."""
        if image is not None and (not isinstance(image, QImage) or image.isNull()):
            raise ValueError("placeholder image must be a non-null QImage or None")
        self._cancel_load()
        self._generation += 1
        self._image = None if image is None else QImage(image)
        self._path = None if path is None else Path(path)
        self._loading = False
        self._error = None
        self._suspended = False
        if self._catalog.current is None:
            self._present_or_blank()
        else:
            self._publish()

    def suspend(self) -> None:
        """Yield empty-catalog presentation to an explicit host scene."""
        self._suspended = True
        self._deactivate()

    def drag_out_allowed(self) -> bool | None:
        """Return placeholder drag policy while active, otherwise ``None``."""
        return bool(self._settings.drag_out_enabled) if self._active else None

    def shutdown(self) -> None:
        """Cancel decoding and release temporary interaction policy."""
        self._cancel_load()
        self._deactivate()

    def _selection_changed(self, entry: ViewerCatalogEntry | None) -> None:
        """Deactivate for real content or resume when the catalog becomes empty."""
        self._suspended = False
        if entry is not None:
            self._deactivate()
            return
        self._present_or_blank()

    def _begin_load(self, path: Path | None) -> None:
        """Replace any prior decode request with one generation-checked load."""
        self._cancel_load()
        self._generation += 1
        self._path = path
        self._image = None
        self._error = None
        if path is None:
            self._loading = False
            self._present_or_blank()
            return
        worker = _PlaceholderLoadWorker(self._generation, path)
        BaseWorker.connect_queued(worker.signals.finished, self._load_finished)
        BaseWorker.connect_queued(worker.signals.error, self._load_failed)
        self._worker = worker
        self._loading = True
        self._publish()
        try:
            self._handle = self._executor.submit(worker, category="io")
        except Exception:
            self._worker = None
            self._handle = None
            self._loading = False
            self._error = "placeholder decode could not be scheduled"
            logger.exception("Placeholder decode submission failed for %s", path)
            self._present_or_blank()

    def _cancel_load(self) -> None:
        """Cancel the current decode without accepting a late worker result."""
        worker = self._worker
        handle = self._handle
        self._worker = None
        self._handle = None
        if worker is not None:
            worker.cancel()
        if handle is not None:
            self._executor.cancel(handle)

    def _load_finished(self, generation: int, path: Path, image: QImage) -> None:
        """Accept one current successful decode and reject stale results."""
        if generation != self._generation or Path(path) != self._path:
            return
        self._worker = None
        self._handle = None
        self._loading = False
        self._error = None
        self._image = QImage(image)
        self._present_or_blank()

    def _load_failed(self, generation: int, path: Path, reason: str) -> None:
        """Record a current decode failure without disturbing real content."""
        if generation != self._generation or Path(path) != self._path:
            return
        self._worker = None
        self._handle = None
        self._loading = False
        self._error = str(reason)
        self._image = None
        self._present_or_blank()

    def _present_or_blank(self) -> None:
        """Project loaded placeholder content when no catalog image owns the view."""
        if self._catalog.current is not None or self._suspended:
            self._deactivate()
            self._publish()
            return
        image = self._image
        if image is None or image.isNull():
            self._deactivate()
            self._set_scene(None, False)
            self._publish()
            return
        source_id = placeholder_source_id(self._path)
        source = RasterSource.from_image(
            image,
            source_id=source_id,
            path=self._path,
        )
        scene = RenderScene.from_size(
            image.size(),
            (
                RenderLayer(
                    source,
                    layer_id=placeholder_layer_id(source_id),
                    role="placeholder",
                    label="Placeholder",
                ),
            ),
            scene_id=placeholder_scene_id(source_id),
        )
        if self._active:
            self._set_navigation_enabled(True)
        self._set_scene(scene, False)
        self._apply_zoom_policy(image.size())
        self._active = True
        self._set_navigation_enabled(bool(self._settings.panzoom_enabled))
        self._publish()

    def _apply_zoom_policy(self, image_size: QSize) -> None:
        """Apply configured fit, locked zoom, or locked display-size policy."""
        mode = self._settings.zoom_mode
        if mode == "locked_zoom" and self._settings.locked_zoom is not None:
            self._viewport.setZoomAndPan(
                max(float(self._settings.locked_zoom), self._viewport.min_zoom()),
                QPointF(),
            )
            self._viewport.zoom_mode = ViewportZoomMode.CUSTOM
            return
        if mode == "locked_size" and self._settings.locked_size is not None:
            width, height = self._settings.locked_size
            zoom = min(width / image_size.width(), height / image_size.height())
            self._viewport.setZoomAndPan(
                max(float(zoom), self._viewport.min_zoom()),
                QPointF(),
            )
            self._viewport.zoom_mode = ViewportZoomMode.CUSTOM
            return
        self._viewport.setZoomFit()

    def _deactivate(self) -> None:
        """Release temporary interaction restrictions if active."""
        if not self._active:
            return
        self._active = False
        self._set_navigation_enabled(True)
        self._publish()

    def _publish(self) -> None:
        """Publish a detached lifecycle snapshot."""
        self.changed.emit(self.state())
