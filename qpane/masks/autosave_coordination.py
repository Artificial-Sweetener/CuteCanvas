#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Mask autosave lifecycle and signal wiring."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from ..concurrency import TaskExecutorProtocol
from ..core.config_features import MaskConfigSlice, require_mask_config
from ..features import FeatureInstallError
from .autosave import AutosaveManager
from .mask import MaskAssetStore
from .mask_controller import MaskController

if TYPE_CHECKING:
    from ..qpane import QPane

logger = logging.getLogger(__name__)


class MaskAutosaveCoordinator:
    """Own autosave installation and signal lifecycle for the mask feature."""

    def __init__(
        self,
        *,
        qpane: QPane,
        mask_assets: MaskAssetStore,
        mask_controller: MaskController,
        executor: TaskExecutorProtocol,
        publish_status: Callable[..., None],
    ) -> None:
        """Bind the feature collaborators required for autosave wiring."""
        self._qpane = qpane
        self._mask_assets = mask_assets
        self._mask_controller = mask_controller
        self._executor = executor
        self._publish_status = publish_status
        self._connected_manager: AutosaveManager | None = None
        self._active_save_slot = None
        self._connecting = False
        self._disconnecting = False

    def applyConfig(self, config: MaskConfigSlice) -> None:
        """Propagate configuration and refresh wiring."""
        manager = self._qpane.autosaveManager()
        if manager is not None:
            manager.applyConfig(config)
        self.refresh()

    def refresh(self) -> None:
        """Match autosave installation to current feature configuration."""
        if not should_enable_mask_autosave(self._qpane):
            self._disconnect(force=True)
            return
        manager = self._qpane.autosaveManager()
        if not isinstance(manager, AutosaveManager):
            manager = AutosaveManager(
                mask_manager=self._mask_assets,
                settings=require_mask_config(self._qpane.settings),
                get_current_image_path=lambda: self._qpane.currentImagePath,
                executor=self._executor,
                diagnostics_dirty=lambda domain="mask": self._qpane.diagnostics().set_dirty(
                    domain
                ),
                parent=self._qpane,
            )
            self._qpane.attachAutosaveManager(manager)
        self._connect(manager)

    def refresh_and_report(self) -> None:
        """Refresh autosave wiring and publish its resulting state."""
        self.refresh()
        manager = self._qpane.autosaveManager()
        active = should_enable_mask_autosave(self._qpane) and isinstance(
            manager, AutosaveManager
        )
        state = "enabled" if active else "disabled"
        manager_label = type(manager).__name__ if manager is not None else "None"
        self._publish_status(
            f"Mask autosave {state} (manager={manager_label}).",
            label="Mask Autosave",
        )

    def _connect(self, manager: AutosaveManager) -> None:
        """Connect one autosave manager exactly once."""
        if self._connected_manager is manager or self._connecting:
            return
        self._connecting = True
        try:
            self._disconnect(force=False)
            controller = self._mask_controller
            controller.mask_updated.connect(manager.scheduleSave)
            controller.active_mask_properties_changed.connect(self._save_blank_mask)
            save_slot = self._qpane._masks_controller.on_mask_saved
            manager.saveCompleted.connect(save_slot)
            manager.saveCompleted.connect(self._handle_save_completed)
            manager.saveFailed.connect(self._handle_save_failed)
            self._active_save_slot = save_slot
            self._connected_manager = manager
        finally:
            self._connecting = False

    def _disconnect(self, *, force: bool) -> None:
        """Disconnect signal wiring and optionally detach the manager."""
        if self._disconnecting:
            return
        self._disconnecting = True
        manager = self._connected_manager
        try:
            if manager is not None:
                for signal, slot in (
                    (self._mask_controller.mask_updated, manager.scheduleSave),
                    (
                        self._mask_controller.active_mask_properties_changed,
                        self._save_blank_mask,
                    ),
                ):
                    try:
                        signal.disconnect(slot)
                    except (TypeError, RuntimeError):
                        logger.debug("Autosave signal was already disconnected.")
                if self._active_save_slot is not None:
                    try:
                        manager.saveCompleted.disconnect(self._active_save_slot)
                    except (TypeError, RuntimeError):
                        logger.debug("Autosave completion was already disconnected.")
                for signal, slot in (
                    (manager.saveCompleted, self._handle_save_completed),
                    (manager.saveFailed, self._handle_save_failed),
                ):
                    try:
                        signal.disconnect(slot)
                    except (TypeError, RuntimeError):
                        logger.debug("Autosave status signal was already disconnected.")
            self._connected_manager = None
            self._active_save_slot = None
            if force and self._qpane.autosaveManager() is manager:
                self._qpane.detachAutosaveManager()
        finally:
            self._disconnecting = False

    def _save_blank_mask(self) -> None:
        """Request creation-time persistence for the active blank mask."""
        manager = self._qpane.autosaveManager()
        active_id = self._mask_controller.get_active_mask_id()
        image = self._qpane.original_image
        if manager is None or active_id is None or image is None or image.isNull():
            return
        manager.saveBlankMask(str(active_id), image.size())

    def _handle_save_completed(self, mask_id: str, path: str) -> None:
        """Publish successful autosave completion for diagnostics."""
        self._publish_status(
            f"Autosaved mask {mask_id} to {path}",
            label="Mask Autosave",
        )

    def _handle_save_failed(self, mask_id: str, path: str, error: Exception) -> None:
        """Publish autosave failure details for diagnostics."""
        self._publish_status(
            f"Autosave failed for mask {mask_id}: {error}",
            label="Mask Autosave Error",
        )


def should_enable_mask_autosave(qpane: QPane) -> bool:
    """Return whether mask autosave is enabled and the feature is installed."""
    try:
        config = require_mask_config(qpane.settings)
    except FeatureInstallError:
        return False
    return bool(config.mask_autosave_enabled and qpane.mask_service is not None)
