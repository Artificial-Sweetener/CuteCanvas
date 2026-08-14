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

"""SAM feature installer and diagnostics wiring under qpane.masks."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QPoint

from cutecanvas.sam.segmentation_request import SmartSegmentationRequest
from cutecanvas.tools.smart_segmentation import (
    SmartMaskTool,
    SmartSelectTool,
    connect_smart_segmentation_signals,
    disconnect_smart_segmentation_signals,
)
from qpane.sdk.features import FeatureInstallError
from qpane.sdk.types import DiagnosticRecord

from ..core.config import SAM_DEFAULT_MODEL_HASH, SAM_DEFAULT_MODEL_URL
from ..core.config_features import require_sam_config

logger = logging.getLogger(__name__)

_SAM_HASH_WARNING_EMITTED = False


if TYPE_CHECKING:
    from ..canvas import CuteCanvas


def install_sam_feature(qpane: CuteCanvas, device: str | None = None) -> None:
    """Install SAM support without loading predictor dependencies eagerly."""
    hooks = qpane.hooks
    try:
        from cutecanvas.sam.service import (
            SamDependencyError,
            ensure_checkpoint,
            resolve_checkpoint_path,
        )
    except ImportError as exc:
        raise FeatureInstallError(
            "Failed to import SAM services.",
            hint="Install the SAM extras via 'pip install cutecanvas[sam]' and verify GPU tooling.",
        ) from exc
    try:
        hooks.registerTool(
            qpane.CONTROL_MODE_SMART_SELECT,
            SmartSelectTool,
            on_connect=connect_smart_segmentation_signals,
            on_disconnect=disconnect_smart_segmentation_signals,
        )
    except ValueError:
        pass
    try:
        hooks.registerTool(
            qpane.CONTROL_MODE_SMART_MASK,
            SmartMaskTool,
            on_connect=connect_smart_segmentation_signals,
            on_disconnect=disconnect_smart_segmentation_signals,
        )
    except ValueError:
        pass
    from cutecanvas.sam.checkpoint import CheckpointProgress
    from cutecanvas.sam.checkpoint_coordination import CheckpointAcquisition
    from cutecanvas.sam.manager import SamManager

    sam_config = require_sam_config(qpane.settings)
    sam_device = sam_config.sam_device if device is None else device
    download_mode = str(sam_config.sam_download_mode or "").strip().lower()
    model_url = sam_config.sam_model_url
    expected_hash = _resolve_expected_hash(
        sam_config.sam_model_hash,
        sam_model_path=sam_config.sam_model_path,
        model_url=model_url,
    )
    _warn_on_unverified_custom_url(model_url, expected_hash)
    try:
        checkpoint_path = resolve_checkpoint_path(sam_config.sam_model_path)
    except SamDependencyError as exc:
        raise FeatureInstallError(
            str(exc),
            hint="Install the SAM extras via 'pip install cutecanvas[sam]' and verify GPU tooling.",
        ) from exc

    def _emit_checkpoint_status(status: str) -> None:
        """Emit a SAM checkpoint status update via the CuteCanvas signal."""
        qpane.samCheckpointStatusChanged.emit(status, checkpoint_path)

    def _emit_checkpoint_progress(progress: CheckpointProgress) -> None:
        """Emit a SAM checkpoint progress update via the CuteCanvas signal."""
        qpane.samCheckpointProgress.emit(
            progress.downloaded,
            progress.total,
        )

    acquisition: CheckpointAcquisition | None = None
    checkpoint_ready_callbacks: list[Callable[[], None]] = []
    if checkpoint_path.exists():
        _emit_checkpoint_status("ready")
    elif download_mode == "disabled":
        try:
            checkpoint_path = ensure_checkpoint(
                checkpoint_path,
                download_mode="disabled",
                model_url=model_url,
                expected_hash=expected_hash,
            )
            _emit_checkpoint_status("ready")
        except SamDependencyError as exc:
            _emit_checkpoint_status("missing")
            raise FeatureInstallError(
                str(exc),
                hint=(
                    "Provide a checkpoint at sam_model_path or enable checkpoint "
                    "acquisition."
                ),
            ) from exc
    else:
        _emit_checkpoint_status("downloading")
        acquisition = CheckpointAcquisition(
            execution_scope=qpane._execution_binding.scope,
            parent=qpane,
        )

        def _handle_download_finished(_path: Path) -> None:
            """Publish checkpoint readiness after owner-context adoption."""
            _emit_checkpoint_status("ready")
            for callback in tuple(checkpoint_ready_callbacks):
                callback()

        def _handle_download_error(error: BaseException) -> None:
            """Publish terminal checkpoint acquisition failure."""
            logger.error(
                "SAM checkpoint acquisition failed for %s: %s",
                checkpoint_path,
                error,
            )
            _emit_checkpoint_status("failed")

        acquisition.request(
            checkpoint_path,
            download_mode=download_mode,
            model_url=model_url,
            expected_hash=expected_hash,
            progress=_emit_checkpoint_progress,
            completed=_handle_download_finished,
            failed=_handle_download_error,
        )
    sam_manager = SamManager(
        parent=qpane,
        device=sam_device,
        execution_scope=(
            qpane._execution_binding.document_runtime.native_execution_scope()
        ),
        cache_limit=sam_config.sam_cache_limit,
        checkpoint_path=checkpoint_path,
        checkpoint_acquisition=acquisition,
    )
    qpane.attachSamManager(sam_manager)
    hooks.register_diagnostics_provider(
        _sam_detail_diagnostics_provider,
        domain="sam",
        tier="detail",
    )
    hooks.register_diagnostics_provider(
        _sam_summary_diagnostics_provider,
        domain="sam",
        tier="detail",
    )
    tm_signals = qpane._tools_manager.signals

    def _prepare_active_raster(*_args: object) -> None:
        """Warm the predictor for the active document raster resource."""
        raster = qpane.activeRasterResolver().resolve(
            preferred_layer_id=(
                None
                if qpane.selectedLayer() is None
                else qpane.selectedLayer().layer_id
            )
        )
        if raster is None:
            return
        manager = qpane.samManager()
        if manager is not None:
            manager.requestPredictor(
                raster.image,
                raster.resource_id,
                source_path=raster.source_path,
            )

    def _handle_region_selected(request: object) -> None:
        """Forward one raster-bound rectangular prompt to SAM."""
        manager = qpane.samManager()
        if manager is None:
            return
        if not isinstance(request, SmartSegmentationRequest):
            logger.warning(
                "Ignoring smart-select request: unexpected request type %s",
                type(request).__name__,
            )
            return
        manager.generateMaskFromBox(
            request.resource_id,
            np.asarray(request.bounds),
            erase_mode=request.erase,
            context=request,
        )

    def _handle_component_adjustment(mask_point: QPoint, grow: bool) -> None:
        """Adjust components at the mask-local point emitted by the tool."""
        service = getattr(qpane, "mask_service", None)
        if service is None:
            return
        active_mask_id = service.getActiveMaskId()
        if mask_point is None or active_mask_id is None:
            return
        new_surface = service.adjust_mask_component(
            active_mask_id,
            mask_point,
            grow=grow,
        )
        if new_surface is None:
            return
        if not service.apply_mask_surface(active_mask_id, new_surface):
            return
        qpane.markDirty()
        qpane.update()

    tm_signals.smart_segmentation_requested.connect(_handle_region_selected)
    tm_signals.mask_component_adjustment_requested.connect(_handle_component_adjustment)
    qpane.compositionSelectionChanged.connect(_prepare_active_raster)
    qpane.selectedLayerChanged.connect(_prepare_active_raster)
    checkpoint_ready_callbacks.append(_prepare_active_raster)
    _prepare_active_raster()


def _resolve_expected_hash(
    raw_hash: object,
    *,
    sam_model_path: str | None,
    model_url: str,
) -> str | None:
    """Return the hash to verify for the configured SAM checkpoint settings."""
    normalized = None
    if isinstance(raw_hash, str):
        candidate = raw_hash.strip()
        if candidate:
            if candidate.lower() == "default":
                normalized = SAM_DEFAULT_MODEL_HASH
            else:
                normalized = candidate
    if (
        normalized is None
        and sam_model_path is None
        and model_url == SAM_DEFAULT_MODEL_URL
    ):
        normalized = SAM_DEFAULT_MODEL_HASH
    return normalized


def _warn_on_unverified_custom_url(
    model_url: str,
    expected_hash: str | None,
) -> None:
    """Warn once when a custom model URL is used without hash verification."""
    global _SAM_HASH_WARNING_EMITTED
    if _SAM_HASH_WARNING_EMITTED:
        return
    if expected_hash is not None:
        return
    if model_url == SAM_DEFAULT_MODEL_URL:
        return
    logger.warning(
        "SAM model URL is custom and sam_model_hash is unset; "
        "checkpoint downloads will not be integrity-checked."
    )
    _SAM_HASH_WARNING_EMITTED = True


def _sam_summary_diagnostics_provider(
    qpane: CuteCanvas,
) -> tuple[DiagnosticRecord, ...]:
    """Expose SAM cache usage and readiness for the SAM detail overlay tier."""
    accessor = getattr(qpane, "samManager", None)
    manager = accessor() if callable(accessor) else None
    if manager is None:
        return ()
    records: list[DiagnosticRecord] = [
        DiagnosticRecord("SAM|Cache", str(manager.getCachedPredictorCount()))
    ]
    delegate = None
    workflow = None
    accessor = getattr(qpane, "masks", None)
    if callable(accessor):
        try:
            workflow = accessor()
        except RuntimeError:
            workflow = None
    if workflow is not None:
        try:
            delegate = workflow.sam_delegate()
        except RuntimeError:
            delegate = None
    active_predictor = (
        getattr(delegate, "activePredictor", None) if delegate is not None else None
    )
    state = "Ready" if active_predictor is not None else "Idle"
    records.append(DiagnosticRecord("SAM|State", state))
    return tuple(records)


def _sam_detail_diagnostics_provider(qpane: CuteCanvas) -> tuple[DiagnosticRecord, ...]:
    """Return the worker-pool diagnostics rows for the SAM detail tier."""
    accessor = getattr(qpane, "samManager", None)
    manager = accessor() if callable(accessor) else None
    if manager is None:
        return ()
    records: list[DiagnosticRecord] = []
    thread_pool = getattr(manager, "thread_pool", None)
    if thread_pool is not None:
        try:
            active_count = thread_pool.activeThreadCount()
        except RuntimeError:
            active_count = None
        if active_count is not None:
            records.append(DiagnosticRecord("SAM|Active Jobs", str(active_count)))
        try:
            max_threads = thread_pool.maxThreadCount()
        except RuntimeError:
            max_threads = None
        if max_threads is not None:
            records.append(DiagnosticRecord("SAM|Max Threads", str(max_threads)))
    return tuple(records)
