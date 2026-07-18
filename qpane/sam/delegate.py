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

"""Wire the SAM manager lifecycle and signals into QPane collaborators."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

import numpy as np

logger = logging.getLogger(__name__)


if TYPE_CHECKING:  # pragma: no cover

    from ..cache.registry import CacheRegistry
    from ..qpane import QPane
    from ..sam import SamManager
    from ..swap.delegate import SwapDelegate


class SamDelegate:
    """Route SAM manager lifecycle through QPane collaborators without exposing view internals."""

    def __init__(
        self,
        *,
        qpane: QPane,
        swap_delegate: SwapDelegate,
        cache_registry: CacheRegistry | None,
    ) -> None:
        """Store collaborators used to manage the SAM manager lifecycle.

        Args:
            qpane: Owning qpane used for UI updates and mask dispatch.
            swap_delegate: Swap delegate notified when the SAM manager attaches or detaches.
            cache_registry: Optional cache registry that should receive the manager.
        """
        self._qpane = qpane
        self._swap_delegate = swap_delegate
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
        """Predictor prepared for the QPane's current image, if available."""
        return self._active_predictor

    def updateCacheRegistry(self, registry: CacheRegistry | None) -> None:
        """Store the cache registry reference and attach the active SAM manager into it."""
        self._cache_registry = registry
        if registry is not None and self._manager is not None:
            registry.attachSamManager(self._manager)

    def attachManager(self, sam_manager: SamManager) -> None:
        """Attach a SAM manager, subscribe to its signals, and refresh QPane policies.

        Raises:
            RuntimeError: When a SAM manager is already attached.

        Side effects:
            Registers the manager with swap/caches, resets predictors, and reapplies QPane cache settings.
        """
        if self._manager is not None:
            logger.error(
                "attachSamManager called while a SAM manager is already attached (current=%s, incoming=%s)",
                type(self._manager).__name__,
                type(sam_manager).__name__,
            )
            raise RuntimeError("SAM manager already attached")
        self._manager = sam_manager
        self._swap_delegate.on_sam_manager_attached(sam_manager)
        self.resetActivePredictor()
        sam_manager.predictorReady.connect(self._on_predictor_ready)
        sam_manager.maskReady.connect(self._on_sam_mask_ready)
        sam_manager.predictorLoadFailed.connect(self._on_sam_predictor_failed)
        qpane = self._qpane
        qpane.refreshMaskAutosavePolicy()
        if self._cache_registry is not None:
            self._cache_registry.attachSamManager(sam_manager)
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
        self._swap_delegate.on_sam_manager_detached()
        self._manager = None
        self.resetActivePredictor()
        qpane = self._qpane
        qpane.refreshMaskAutosavePolicy()
        qpane.applyCacheSettings()

    def resetActivePredictor(self) -> None:
        """Drop any predictor cached for the current image."""
        self._active_predictor = None

    def predict_mask_from_box(self, bbox: np.ndarray) -> np.ndarray | None:
        """Run box inference through the SAM service boundary."""
        predictor = self._active_predictor
        if predictor is None:
            return None
        from .service import predict_mask_from_box

        return predict_mask_from_box(predictor, bbox)

    def _on_predictor_ready(self, predictor, image_id: uuid.UUID) -> None:
        """Activate the predictor when it aligns with the current image and refresh the view."""
        qpane = self._qpane
        if image_id == qpane.currentImageID():
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
        if image_id == qpane.currentImageID():
            self.resetActivePredictor()
            qpane.refreshCursor()
            qpane.update()
