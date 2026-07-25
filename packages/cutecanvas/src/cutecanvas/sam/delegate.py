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

"""Wire the SAM manager lifecycle and signals into CuteCanvas collaborators."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

import numpy as np
from qpane.sdk.cache import CachePriority, KeyedCacheConsumer

logger = logging.getLogger(__name__)


if TYPE_CHECKING:  # pragma: no cover

    from qpane.sdk.cache import CacheRegistry

    from ..canvas import CuteCanvas
    from ..sam import SamManager


class SamDelegate:
    """Route SAM manager lifecycle through CuteCanvas collaborators without exposing view internals."""

    def __init__(
        self,
        *,
        qpane: CuteCanvas,
        cache_registry: CacheRegistry | None,
    ) -> None:
        """Store collaborators used to manage the SAM manager lifecycle.

        Args:
            qpane: Owning qpane used for UI updates and mask dispatch.
            cache_registry: Optional cache registry that should receive the manager.
        """
        self._qpane = qpane
        self._cache_registry = cache_registry
        self._manager: SamManager | None = None
        self._active_predictor = None
        self._warned_missing_mask_service = False

    @property
    def manager(self) -> SamManager | None:
        """Currently attached SAM manager, if any."""
        return self._manager

    @property
    def activePredictor(self) -> object | None:
        """Predictor prepared for the CuteCanvas's current image, if available."""
        return self._active_predictor

    def updateCacheRegistry(self, registry: CacheRegistry | None) -> None:
        """Store the cache registry reference and attach the active SAM manager into it."""
        self._cache_registry = registry
        if registry is not None and self._manager is not None:
            self._attach_cache_consumer(registry, self._manager)

    def attachManager(self, sam_manager: SamManager) -> None:
        """Attach a SAM manager, subscribe to its signals, and refresh CuteCanvas policies.

        Raises:
            RuntimeError: When a SAM manager is already attached.

        Side effects:
            Registers the manager with caches, resets predictors, and reapplies
            CuteCanvas cache settings.
        """
        if self._manager is not None:
            logger.error(
                "attachSamManager called while a SAM manager is already attached (current=%s, incoming=%s)",
                type(self._manager).__name__,
                type(sam_manager).__name__,
            )
            raise RuntimeError("SAM manager already attached")
        self._manager = sam_manager
        self.resetActivePredictor()
        sam_manager.predictorReady.connect(self._on_predictor_ready)
        sam_manager.maskReady.connect(self._on_sam_mask_ready)
        sam_manager.predictorLoadFailed.connect(self._on_sam_predictor_failed)
        qpane = self._qpane
        qpane.refreshMaskAutosavePolicy()
        if self._cache_registry is not None:
            self._attach_cache_consumer(self._cache_registry, sam_manager)
        qpane.applyCacheSettings()

    def detachManager(self) -> None:
        """Detach the active SAM manager, disconnect signals, and reset predictor state."""
        manager = self._manager
        if manager is None:
            return
        try:
            manager.predictorReady.disconnect(self._on_predictor_ready)
            manager.maskReady.disconnect(self._on_sam_mask_ready)
            manager.predictorLoadFailed.disconnect(self._on_sam_predictor_failed)
        except (TypeError, RuntimeError):
            pass
        self._manager = None
        self.resetActivePredictor()
        qpane = self._qpane
        qpane.refreshMaskAutosavePolicy()
        qpane.applyCacheSettings()

    def resetActivePredictor(self) -> None:
        """Drop any predictor cached for the current image."""
        self._active_predictor = None

    @staticmethod
    def _attach_cache_consumer(registry: CacheRegistry, manager: SamManager) -> None:
        """Adapt the SAM cache into QPane's source-neutral cache coordinator."""

        def connect_usage_events(changed, cleared) -> None:
            """Publish predictor cache additions, removals, and clears."""
            manager.predictorReady.connect(lambda *_args: changed())
            manager.predictorRemoved.connect(lambda *_args: changed())
            manager.predictorCacheCleared.connect(cleared)

        registry.attach_extension(
            "models",
            lambda coordinator: KeyedCacheConsumer(
                coordinator,
                consumer_id="models",
                priority=CachePriority.BACKGROUND_MODELS,
                get_usage=manager.cache_usage_bytes,
                set_admission_guard=lambda guard: (
                    manager.set_admission_guard(guard)
                    if callable(getattr(manager, "set_admission_guard", None))
                    else None
                ),
                keys=lambda: tuple(manager.predictorImageIds()),
                remove=lambda key: manager.removeFromCache(key),
                connect_usage_events=connect_usage_events,
            ),
        )

    def request_mask_from_box(
        self,
        bbox: np.ndarray,
        *,
        erase_mode: bool,
    ) -> bool:
        """Queue box inference through the manager's native session."""
        reference = self._active_predictor
        manager = self._manager
        image_id = getattr(reference, "image_id", None)
        if manager is None or image_id is None:
            return False
        return manager.generateMaskFromBox(image_id, bbox, erase_mode=erase_mode)

    def _on_predictor_ready(self, predictor, image_id: uuid.UUID) -> None:
        """Activate a predictor that matches the active raster resource."""
        qpane = self._qpane
        raster = qpane.activeRasterResolver().resolve(
            preferred_layer_id=(
                None
                if qpane.selectedLayer() is None
                else qpane.selectedLayer().layer_id
            )
        )
        if raster is not None and image_id == raster.resource_id:
            self._active_predictor = predictor
            qpane.refreshCursor()
            qpane.update()

    def _on_sam_mask_ready(
        self, mask_array_uint8: np.ndarray | None, bbox: np.ndarray, erase_mode: bool
    ) -> None:
        """Forward generated mask data to the mask service when available and ignore missing services gracefully."""
        qpane = self._qpane
        service = qpane._masks_controller.mask_service()
        if service is not None:
            service.handleGeneratedMask(mask_array_uint8, bbox, erase_mode)
            self._warned_missing_mask_service = False
        elif not self._warned_missing_mask_service:
            logger.warning("SAM mask dropped because mask service is unavailable")
            self._warned_missing_mask_service = True

    def _on_sam_predictor_failed(self, image_id: uuid.UUID, message: str) -> None:
        """Log predictor failures and clear the active predictor for the displayed image."""
        qpane = self._qpane
        logger.error("SAM predictor failed for %s: %s", image_id, message)
        raster = qpane.activeRasterResolver().resolve(
            preferred_layer_id=(
                None
                if qpane.selectedLayer() is None
                else qpane.selectedLayer().layer_id
            )
        )
        if raster is not None and image_id == raster.resource_id:
            self.resetActivePredictor()
            qpane.refreshCursor()
            qpane.update()
