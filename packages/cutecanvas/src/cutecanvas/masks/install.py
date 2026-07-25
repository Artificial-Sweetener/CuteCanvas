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
        stroke_diagnostics=diagnostics_tracker,
        structure_changed=qpane._handle_raster_structure_changed,
        content_changed=qpane._handle_scene_source_changed,
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

    def _handle_mask_updated(mask_id, rect=None):
        """Mark the CuteCanvas dirty when mask scene content changes."""
        if rect is None or rect.isNull() or rect.isEmpty():
            qpane.markDirty()
        else:
            qpane.markDirty(dirty_rect=rect)
        qpane.update()

    controller.mask_updated.connect(_handle_mask_updated)
    controller.active_mask_properties_changed.connect(qpane.refreshCursor)
    controller.active_mask_properties_changed.connect(
        qpane._synchronize_active_mask_layer_selection
    )
