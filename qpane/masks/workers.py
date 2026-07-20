#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Background workers for derived mask rasters."""

from __future__ import annotations

import logging
import uuid
import weakref
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING

from PySide6.QtCore import QMetaObject, QRect, QRunnable, Qt
from PySide6.QtGui import QColor, QImage

from ..concurrency import BaseWorker
from .mask import MaskAssetStore
from .mask_controller import MaskController

if TYPE_CHECKING:
    from .render_coordination import MaskRenderWorkCoordinator

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PrefetchedOverlay:
    """Colorized overlay produced by a worker."""

    mask_id: uuid.UUID
    render_revision: int
    image: QImage
    scaled: tuple[tuple[float, QImage], ...] = ()
    colorize_duration_ms: float | None = None


class MaskPrefetchWorker(QRunnable, BaseWorker):
    """Background worker that prepares colorized mask renders off the UI thread."""

    def __init__(
        self,
        *,
        image_id: uuid.UUID,
        mask_ids: Sequence[uuid.UUID],
        mask_manager: MaskAssetStore,
        controller: MaskController,
        coordinator: MaskRenderWorkCoordinator,
        current_image_id: uuid.UUID | None,
        scales: Sequence[float] | None = None,
    ) -> None:
        """Record collaborators required to pre-colorize mask renders."""
        QRunnable.__init__(self)
        BaseWorker.__init__(self, logger=logger.getChild("MaskPrefetchWorker"))
        self._image_id = image_id
        manager = mask_manager
        masks = list(mask_ids)
        # Always process the current image first when available so scaled overlays are ready.
        current_id = current_image_id
        if current_id in masks:
            masks.remove(current_id)
            masks.insert(0, current_id)
        self._mask_ids = tuple(masks)
        self._mask_manager = manager
        self._controller = controller
        self._coordinator_ref = weakref.ref(coordinator)
        self._scales: tuple[float, ...] = tuple(scales or ())
        self._task_id: str | None = None
        self.setAutoDelete(False)

    def set_task_id(self, task_id: str) -> None:
        """Capture the executor task identifier for cancellation tracking."""
        self._task_id = task_id

    def run(self) -> None:
        """Perform the overlay prefetch work off the UI thread."""
        coordinator = self._coordinator_ref()
        if coordinator is None:
            self.emit_finished(True)
            return
        warmed: list[PrefetchedOverlay] = []
        failures: dict[uuid.UUID, str] = {}
        error: BaseException | None = None
        start = monotonic()
        try:
            for mask_id in self._mask_ids:
                if self.is_cancelled:
                    error = RuntimeError("prefetch cancelled")
                    break
                layer = self._mask_manager.get_layer(mask_id)
                if layer is None or layer.surface.is_null():
                    continue
                render_revision = self._controller.renders.render_revision(mask_id)
                try:
                    if self.is_cancelled:
                        error = RuntimeError("prefetch cancelled")
                        break
                    colorize_started = monotonic()
                    image = self._controller.renders.prepare_image_detached(
                        layer, mask_id=mask_id
                    )
                    colorize_duration_ms = (monotonic() - colorize_started) * 1000.0
                except Exception as exc:  # noqa: BLE001 - isolate one corrupt mask
                    failures[mask_id] = str(exc)
                    continue
                if image is not None:
                    scaled_outputs: list[tuple[float, QImage]] = []
                    for scale_key in self._scales:
                        if self.is_cancelled:
                            error = RuntimeError("prefetch cancelled")
                            break
                        target_size = self._controller.renders.target_scaled_size(
                            image.size(), scale_key
                        )
                        if target_size == image.size() or target_size.isEmpty():
                            continue
                        scaled_image = image.scaled(
                            target_size,
                            Qt.AspectRatioMode.IgnoreAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                        if scaled_image.isNull():
                            continue
                        scaled_outputs.append((scale_key, scaled_image))
                    if error is not None:
                        break
                    warmed.append(
                        PrefetchedOverlay(
                            mask_id=mask_id,
                            render_revision=render_revision,
                            image=image,
                            scaled=tuple(scaled_outputs),
                            colorize_duration_ms=colorize_duration_ms,
                        )
                    )
        except Exception as exc:  # pragma: no cover - defensive
            error = exc
            logger.exception("Mask prefetch worker failed for image %s", self._image_id)
        duration_ms = (monotonic() - start) * 1000.0
        self._dispatch_finalize(tuple(warmed), failures, duration_ms, error)
        success = error is None and not self.is_cancelled
        self.emit_finished(success, payload=None, error=error)

    def _dispatch_finalize(
        self,
        warmed: tuple[PrefetchedOverlay, ...],
        failures: Mapping[uuid.UUID, str],
        duration_ms: float,
        error: BaseException | None,
    ) -> None:
        """Deliver prefetch completion on the main thread."""
        coordinator = self._coordinator_ref()
        if coordinator is None:
            return

        def finalize() -> None:
            """Apply warmed overlays and propagate prefetch results to the service."""
            owner = self._coordinator_ref()
            if owner is None:
                return
            owner.consume_prefetch_results(
                image_id=self._image_id,
                warmed=warmed,
                failures=dict(failures),
                duration_ms=duration_ms,
                error=error,
                task_id=self._task_id,
            )

        executor = self._executor
        if executor is not None and hasattr(executor, "dispatch_to_main_thread"):
            try:
                executor.dispatch_to_main_thread(
                    finalize, category="mask_prefetch_main"
                )
                return
            except AttributeError:
                pass
        QMetaObject.invokeMethod(
            self._controller,
            finalize,
            Qt.ConnectionType.QueuedConnection,
        )


class MaskSnippetWorker(QRunnable, BaseWorker):
    """Background worker that colorizes dirty mask snippets off the UI thread."""

    def __init__(
        self,
        *,
        mask_id: uuid.UUID,
        render_revision: int,
        dirty_rect: QRect,
        snippet: QImage,
        color: QColor,
        controller: MaskController,
        coordinator: MaskRenderWorkCoordinator,
    ) -> None:
        """Capture snippet metadata and controller hooks for async colorization."""
        QRunnable.__init__(self)
        BaseWorker.__init__(self, logger=logger.getChild("MaskSnippetWorker"))
        self._mask_id = mask_id
        self._render_revision = render_revision
        self._dirty_rect = QRect(dirty_rect)
        self._snippet = snippet
        self._color = QColor(color)
        self._controller = controller
        self._coordinator_ref = weakref.ref(coordinator)
        self.setAutoDelete(False)

    def run(self) -> None:
        """Colorize the provided snippet and dispatch results back to Qt."""
        coordinator = self._coordinator_ref()
        if coordinator is None:
            self.emit_finished(True)
            return
        if self.is_cancelled:
            self.emit_finished(True)
            return
        colorized_image: QImage | None = None
        colorize_duration_ms: float | None = None
        error: BaseException | None = None
        try:
            colorize_started = monotonic()
            colorized_image = self._controller.renders.rasterize_detached(
                self._snippet,
                self._color,
            )
            colorize_duration_ms = (monotonic() - colorize_started) * 1000.0
        except Exception as exc:  # pragma: no cover - defensive
            error = exc
            self.logger.exception(
                "Mask snippet worker failed for mask %s", self._mask_id
            )
        if self.is_cancelled:
            self.emit_finished(True)
            return
        self._dispatch_finalize(colorized_image, colorize_duration_ms)
        self.emit_finished(error is None, error=error)

    def _dispatch_finalize(
        self,
        colorized_image: QImage | None,
        colorize_duration_ms: float | None,
    ) -> None:
        """Deliver snippet colorization results back to the service on the GUI thread."""
        coordinator = self._coordinator_ref()
        if coordinator is None:
            return
        handle = getattr(self, "_handle", None)
        mask_id = self._mask_id
        render_revision = self._render_revision
        rect = QRect(self._dirty_rect)

        def finalize() -> None:
            """Apply snippet outputs and clear bookkeeping safely."""
            owner = self._coordinator_ref()
            if owner is None:
                return
            owner.consume_snippet_result(
                mask_id=mask_id,
                render_revision=render_revision,
                handle=handle,
                dirty_rect=rect,
                colorized_image=colorized_image,
                colorize_duration_ms=colorize_duration_ms,
            )

        executor = getattr(self, "_executor", None)
        if executor is not None and hasattr(executor, "dispatch_to_main_thread"):
            try:
                executor.dispatch_to_main_thread(finalize, category="mask_snippet_main")
                return
            except AttributeError:
                pass
        QMetaObject.invokeMethod(
            self._controller,
            finalize,
            Qt.ConnectionType.QueuedConnection,
        )
