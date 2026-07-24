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

"""Editable-mask activation and deferred overlay-resume coordination."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable

from PySide6.QtCore import QTimer

from .mask import MaskAssetStore
from .mask_controller import MaskController

logger = logging.getLogger(__name__)

_DEFER_ACTIVATION_RATIO = 0.6


class MaskActivationController:
    """Own editable-source selection and deferred activation state."""

    def __init__(
        self,
        *,
        controller: MaskController,
        assets: MaskAssetStore,
        mask_ids_for_composition: Callable[[uuid.UUID], list[uuid.UUID]],
        invalidate_jobs: Callable[..., None],
        promote_to_top: Callable[[uuid.UUID], bool],
        scene_stack_end: Callable[..., int | None],
        route_reorder: Callable[[uuid.UUID, int], bool | None],
        reorder: Callable[[uuid.UUID, uuid.UUID, int], bool],
        prefetch: Callable[..., bool],
        prefetch_pending: Callable[[uuid.UUID], bool],
        publish_status: Callable[..., None],
        resume: Callable[[uuid.UUID | None], None],
        resume_and_update: Callable[[uuid.UUID | None], None],
    ) -> None:
        """Initialize activation with explicit workflow collaborators."""
        self._controller = controller
        self._assets = assets
        self._mask_ids_for_composition = mask_ids_for_composition
        self._invalidate_jobs = invalidate_jobs
        self._promote_to_top = promote_to_top
        self._scene_stack_end = scene_stack_end
        self._route_reorder = route_reorder
        self._reorder = reorder
        self._prefetch = prefetch
        self._prefetch_pending = prefetch_pending
        self._publish_status = publish_status
        self._pending_compositions: set[uuid.UUID] = set()
        self._default_resume_cb = resume
        self._default_resume_update_cb = resume_and_update
        self._default_activation_pending_cb = lambda _image_id=None: None
        self._resume_overlays_cb = resume
        self._resume_overlays_and_update_cb = resume_and_update
        self._activation_pending_cb = self._default_activation_pending_cb
        self._last_status: tuple[str, str] | None = None

    def set_resume_hooks(
        self,
        resume: Callable[[uuid.UUID | None], None] | None,
        resume_and_update: Callable[[uuid.UUID | None], None] | None,
        on_pending: Callable[[uuid.UUID | None], None] | None,
    ) -> None:
        """Override activation resume callbacks used during deferred activation."""
        self._resume_overlays_cb = (
            resume if resume is not None else self._default_resume_cb
        )
        self._resume_overlays_and_update_cb = (
            resume_and_update
            if resume_and_update is not None
            else self._default_resume_update_cb
        )
        self._activation_pending_cb = (
            on_pending
            if on_pending is not None
            else self._default_activation_pending_cb
        )

    def activate(self, mask_id: uuid.UUID | None) -> bool:
        """Select the mask to edit and keep caches in sync.

        Returns:
            bool: True when the mask changed position in the stack during activation.
        """
        previous_active = self._controller.get_active_mask_id()
        if mask_id is None:
            self._invalidate_jobs(
                previous_active, reason="mask_deselected", request_redraw=False
            )
            self._controller.setActiveMaskID(None)
            return True
        if previous_active is not None and previous_active != mask_id:
            self._invalidate_jobs(previous_active, reason="mask_switch")
        was_moved = self._promote_to_top(mask_id)
        self._controller.setActiveMaskID(mask_id)
        return was_moved

    def ensure_top_active(self, composition_id: uuid.UUID | None) -> bool:
        """Ensure the active mask aligns with the current document before brush use."""

        def record_once(message: str, *, label: str) -> None:
            """Emit a status message unless it matches the last entry."""
            status = (label, message)
            if self._last_status == status:
                return
            self._last_status = status
            self._publish_status(message, label=label)

        active_mask_id = self._controller.get_active_mask_id()
        if composition_id is None:
            self._invalidate_jobs(
                active_mask_id, reason="mask_switch", request_redraw=False
            )
            self._controller.setActiveMaskID(None)
            record_once(
                "Brush tool unavailable: no document selected.",
                label="Mask Error",
            )
            return False
        mask_ids = self._mask_ids_for_composition(composition_id)
        if not mask_ids:
            should_defer = self.should_defer(active_mask_id, None)
            self._invalidate_jobs(
                active_mask_id, reason="mask_switch", request_redraw=False
            )
            self._controller.setActiveMaskID(
                None, warm_cache=False, emit_signals=not should_defer
            )
            pending = composition_id in self._pending_compositions
            if pending:
                self._schedule_signals(None, composition_id=composition_id)
            else:
                self._pending_compositions.discard(composition_id)
                try:
                    self._resume_overlays_cb(composition_id)
                except Exception:  # pragma: no cover - defensive guard
                    logger.exception(
                        "Failed to resume overlays after maskless activation"
                    )
            record_once(
                f"Brush tool unavailable: document {composition_id} has no masks.",
                label="Mask Error",
            )
            return False
        prefetch_pending = self._prefetch_pending(composition_id)
        self._pending_compositions.discard(composition_id)
        if active_mask_id in mask_ids:
            if active_mask_id != mask_ids[-1]:
                top_scene_index = self._scene_stack_end(forward=True)
                moved = (
                    self._route_reorder(
                        active_mask_id,
                        top_scene_index,
                    )
                    if top_scene_index is not None
                    else None
                )
                if moved is None:
                    moved = self._reorder(
                        composition_id,
                        active_mask_id,
                        len(mask_ids) - 1,
                    )
                if moved:
                    self._controller.edits.advance_epoch(
                        active_mask_id, reason="mask_reordered"
                    )
            return True
        self._invalidate_jobs(active_mask_id, reason="mask_switch")
        top_mask_id = mask_ids[-1]
        top_scene_index = self._scene_stack_end(forward=True)
        moved = (
            self._route_reorder(top_mask_id, top_scene_index)
            if top_scene_index is not None
            else None
        )
        if moved is None:
            moved = self._reorder(
                composition_id,
                top_mask_id,
                len(mask_ids) - 1,
            )
        if moved:
            self._controller.edits.advance_epoch(top_mask_id, reason="mask_reordered")
        size_defer = self.should_defer(active_mask_id, top_mask_id)
        scheduled_prefetch = False
        if size_defer:
            try:
                scheduled_prefetch = self._prefetch(
                    composition_id,
                    reason="activation",
                )
            except Exception:
                logger.exception(
                    "Failed to prefetch mask renders for %s during activation",
                    composition_id,
                )
            else:
                if scheduled_prefetch:
                    prefetch_pending = True
        should_defer = size_defer or prefetch_pending
        self._controller.setActiveMaskID(
            top_mask_id, warm_cache=not should_defer, emit_signals=not should_defer
        )
        if should_defer:
            self._pending_compositions.add(composition_id)
            self._schedule_signals(
                top_mask_id,
                warm_cache=not prefetch_pending,
                composition_id=composition_id,
            )
        record_once(
            f"Activated mask {top_mask_id} for document {composition_id} before brush use.",
            label="Mask",
        )
        return True

    def is_pending(self, composition_id: uuid.UUID | None) -> bool:
        """Return True while we are waiting on deferred mask activation."""
        if composition_id is None:
            return False
        return composition_id in self._pending_compositions

    def should_defer(
        self,
        previous_mask_id: uuid.UUID | None,
        next_mask_id: uuid.UUID | None,
    ) -> bool:
        """Return True when activation signals should be deferred."""
        if previous_mask_id is None or next_mask_id is None:
            return False
        if previous_mask_id == next_mask_id:
            return False
        next_layer = self._assets.get_layer(next_mask_id)
        if next_layer is None:
            return False
        next_bounds = next_layer.coverage.raster.bounds
        if next_bounds is None:
            return False
        next_pixels = next_bounds.width * next_bounds.height
        if next_pixels <= 0:
            return False
        previous_layer = self._assets.get_layer(previous_mask_id)
        if previous_layer is None:
            return False
        previous_bounds = previous_layer.coverage.raster.bounds
        if previous_bounds is None:
            return False
        previous_pixels = previous_bounds.width * previous_bounds.height
        if previous_pixels <= 0:
            return False
        if next_pixels >= previous_pixels:
            return False
        ratio = next_pixels / previous_pixels
        should_defer = ratio < _DEFER_ACTIVATION_RATIO
        if should_defer:
            logger.info(
                "Deferring mask activation signals: prev=%s (%dx%d) next=%s (%dx%d) ratio=%.3f threshold=%.2f",
                previous_mask_id,
                previous_bounds.width,
                previous_bounds.height,
                next_mask_id,
                next_bounds.width,
                next_bounds.height,
                ratio,
                _DEFER_ACTIVATION_RATIO,
            )
        return should_defer

    def _schedule_signals(
        self,
        mask_id: uuid.UUID | None,
        *,
        warm_cache: bool = False,
        composition_id: uuid.UUID | None = None,
    ) -> None:
        """Emit activation signals once the mask data is ready."""
        controller = self._controller

        def emit_later(
            mid: uuid.UUID | None = mask_id,
            *,
            target_composition_id: uuid.UUID | None = composition_id,
        ) -> None:
            """Emit activation signals after optional cache warmup."""
            try:
                if warm_cache and mid is not None:
                    controller.warm_mask(mid)
                controller.emit_activation_signals(mid)
            finally:
                was_pending = (
                    target_composition_id is not None
                    and target_composition_id in self._pending_compositions
                )
                if target_composition_id is not None:
                    self._pending_compositions.discard(target_composition_id)
                try:
                    callback = (
                        self._resume_overlays_and_update_cb
                        if was_pending
                        else self._resume_overlays_cb
                    )
                    callback(target_composition_id)
                except Exception:
                    logger.exception("Activation resume callback failed")

        try:
            self._activation_pending_cb(composition_id)
        except Exception:
            logger.exception("Activation pending callback failed during scheduling")
        QTimer.singleShot(
            0,
            lambda: emit_later(target_composition_id=composition_id),
        )
