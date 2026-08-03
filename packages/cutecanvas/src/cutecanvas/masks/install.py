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

"""Mask feature installer entry point and helper wiring."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from ..core.config_features import require_mask_config
from .autosave_coordination import should_enable_mask_autosave
from .mask_controller import MaskController
from .mask_diagnostics import MaskStrokeDiagnostics
from .mask_service import MaskService

if TYPE_CHECKING:
    from ..canvas import CuteCanvas

__all__ = [
    "install_mask_feature",
    "should_enable_mask_autosave",
]


def install_mask_feature(qpane: CuteCanvas) -> None:
    """Install mask management subsystems and tool wiring for a CuteCanvas."""
    mask_config = require_mask_config(qpane.settings)
    diagnostics_manager = qpane.diagnostics()
    resources = qpane._project_resources
    if resources is None:
        raise RuntimeError("project resource store is unavailable")
    mask_manager = qpane.document().masks
    live_previews = qpane._execution_binding.document_runtime._mask_live_preview_store
    mask_manager.set_undo_limit(mask_config.mask_undo_limit)
    diagnostics_tracker = MaskStrokeDiagnostics(
        enabled=False,
        dirty_callback=lambda domain="mask": diagnostics_manager.set_dirty(domain),
    )
    mask_controller = MaskController(
        mask_manager,
        source_to_panel_point=qpane.activeMaskLayerCoordinates().source_to_panel,
        config=qpane.settings,
        mask_config=mask_config,
        live_previews=live_previews,
        stroke_diagnostics=diagnostics_tracker,
        structure_changed=qpane._handle_raster_structure_changed,
        render_scale=lambda: qpane.view().viewport.zoom,
    )
    service = MaskService(
        qpane=qpane,
        mask_assets=mask_manager,
        mask_controller=mask_controller,
        config=qpane.settings,
        mask_config=mask_config,
        view_execution_scope=qpane._execution_binding.scope,
        document_execution_scope=(
            qpane._execution_binding.document_runtime.execution_scope
        ),
        latest_requests=(
            qpane._execution_binding.document_runtime._latest_request_registry
        ),
        stroke_diagnostics=diagnostics_tracker,
    )
    qpane.attachMaskService(service)
    service.configureStrokeDiagnostics(qpane.settings)
    controller = service.controller
    live_source_modes: dict[uuid.UUID, bool] = {}
    shared_source_modes: dict[uuid.UUID, bool] = {}

    def _handle_render_dirty(mask_id, rect=None):
        """Apply presentation damage that is already in panel coordinates."""
        if isinstance(mask_id, uuid.UUID):
            live_source = controller.renders.uses_local_live_preview(mask_id)
            if live_source_modes.get(mask_id, False) != live_source:
                live_source_modes[mask_id] = live_source
                qpane._handle_scene_source_changed()
                qpane.markDirty()
                qpane.update()
                return
        else:
            qpane._handle_scene_source_changed()
        if rect is None or rect.isNull() or rect.isEmpty():
            qpane._handle_scene_source_changed()
            qpane.markDirty()
        else:
            qpane.markDirty(dirty_rect=rect)
        qpane.update()

    def _handle_mask_updated(mask_id, rect=None):
        """Recompile durable state while preserving render-owned local damage."""
        if isinstance(mask_id, uuid.UUID):
            live_source = controller.renders.uses_local_live_preview(mask_id)
            live_source_modes[mask_id] = live_source
            if live_source:
                return
        qpane.view().invalidate_content_cache()
        if rect is not None and not rect.isNull() and not rect.isEmpty():
            return
        qpane.markDirty()
        qpane.update()

    def _handle_shared_preview_changed(mask_id, rect):
        """Damage one view after its document-shared transient mask changes."""
        shared_live = live_previews.contains(mask_id)
        if shared_source_modes.get(mask_id, False) != shared_live:
            shared_source_modes[mask_id] = shared_live
            qpane._handle_scene_source_changed()
        controller.renders.notify_live_preview_changed(mask_id, rect)

    controller.render_dirty.connect(_handle_render_dirty)
    controller.mask_updated.connect(_handle_mask_updated)
    live_previews.changed.connect(_handle_shared_preview_changed)
    controller.active_mask_properties_changed.connect(qpane.refreshCursor)
    controller.active_mask_properties_changed.connect(
        qpane._synchronize_active_mask_layer_selection
    )
