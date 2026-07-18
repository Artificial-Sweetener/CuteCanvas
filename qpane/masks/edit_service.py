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

"""Transactional mask editing and undo integration."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import replace
from typing import Any

import numpy as np
from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QImage

from ..catalog.image_utils import (
    numpy_to_qimage_grayscale8,
    qimage_to_numpy_grayscale8,
)
from ..scene.raster import RasterBounds, RasterExtentPolicy
from .mask import MaskAssetStore, MaskLayer
from .mask_diagnostics import MaskStrokeDiagnostics
from .mask_undo import MaskHistoryChange, MaskPatch
from .render_cache import MaskRenderCache
from .stroke_history import MaskStrokeHistorySession
from .stroke_models import MaskStrokeJobResult, MaskStrokeJobSpec, MaskStrokePayload
from .surface import MaskSurfaceSnapshot, WritableMaskRegion

logger = logging.getLogger(__name__)


class MaskEditEpochs:
    """Own async edit epochs used to reject stale worker results."""

    def __init__(self) -> None:
        """Initialize empty per-source epoch state."""
        self.values: dict[uuid.UUID, int] = {}

    def current(self, mask_id: uuid.UUID) -> int:
        """Return the current epoch for a source."""
        return self.values.get(mask_id, 0)

    def advance(self, mask_id: uuid.UUID) -> int:
        """Advance and return a source epoch."""
        next_epoch = self.current(mask_id) + 1
        self.values[mask_id] = next_epoch
        return next_epoch

    def discard(self, mask_id: uuid.UUID) -> None:
        """Forget epoch state for a deleted source."""
        self.values.pop(mask_id, None)


class MaskEditService:
    """Own transactional pixel edits, history commits, and async edit epochs."""

    def __init__(
        self,
        assets: MaskAssetStore,
        renders: MaskRenderCache,
        epochs: MaskEditEpochs,
        *,
        active_mask_id: Callable[[], uuid.UUID | None],
        mask_changed: Callable[[uuid.UUID | None, QRect], None],
        undo_changed: Callable[[uuid.UUID], None],
        structure_changed: Callable[[], None] | None = None,
        diagnostics: MaskStrokeDiagnostics | None = None,
    ) -> None:
        """Initialize editing with explicit state-owner collaborators."""
        self._assets = assets
        self._renders = renders
        self._epochs = epochs
        self._active_mask_id = active_mask_id
        self._mask_changed = mask_changed
        self._undo_changed = undo_changed
        self._structure_changed = structure_changed or (lambda: None)
        self._diagnostics = diagnostics
        self._stroke_history = MaskStrokeHistorySession()

    def _get_layer(self, mask_id: uuid.UUID | None) -> MaskLayer | None:
        """Return the canonical layer for a source id."""
        return None if mask_id is None else self._assets.get_layer(mask_id)

    @staticmethod
    def _layer_is_empty(layer: MaskLayer | None) -> bool:
        """Return whether a layer lacks canonical pixels."""
        return layer is None or layer.surface.is_null()

    def _record_stroke_event(self, event: str) -> None:
        """Record edit diagnostics when configured."""
        if self._diagnostics is not None and event:
            self._diagnostics.record_generation_event(event)

    def async_epoch(self, mask_id: uuid.UUID) -> int:
        """Return the async edit epoch used to reject stale work."""
        return self._epochs.current(mask_id)

    def advance_epoch(self, mask_id: uuid.UUID, *, reason: str | None = None) -> int:
        """Advance and return the sole async edit epoch for ``mask_id``."""
        next_generation = self._epochs.advance(mask_id)
        if reason:
            logger.debug(
                "Mask %s generation advanced to %s (%s).",
                mask_id,
                next_generation,
                reason,
            )
        return next_generation

    def discard_source(self, mask_id: uuid.UUID) -> None:
        """Forget controller generation tracking for `mask_id`."""
        self._epochs.discard(mask_id)
        self._stroke_history.discard(mask_id)
        self._renders.discard_source(mask_id)

    def prepare_writable_region(
        self,
        mask_id: uuid.UUID,
        requested: RasterBounds,
    ) -> WritableMaskRegion | None:
        """Apply source extent policy and capture structural stroke history."""
        layer = self._get_layer(mask_id)
        if layer is None:
            return None
        surface = layer.surface
        current = surface.bounds
        will_expand = bool(
            surface.extent_policy is RasterExtentPolicy.EXPAND_ON_WRITE
            and (current is None or not current.contains(requested))
        )
        before = surface.snapshot() if will_expand else None
        storage_request = (
            self._reserved_stroke_bounds(current, requested)
            if will_expand and current is not None
            else requested
        )
        storage_write = surface.ensure_writable(storage_request)
        writable = WritableMaskRegion(
            requested=requested,
            writable=(
                requested
                if storage_write.after_bounds is not None
                and storage_write.after_bounds.contains(requested)
                else storage_write.writable
            ),
            before_bounds=storage_write.before_bounds,
            after_bounds=storage_write.after_bounds,
        )
        if writable.expanded and before is not None:
            self._stroke_history.capture_structure(mask_id, before)
            self.advance_epoch(mask_id, reason="stroke_surface_expanded")
            self._renders.reframe_layer(
                layer,
                before=writable.before_bounds,
                after=writable.after_bounds,
            )
            self._structure_changed()
            self._mask_changed(mask_id, QRect())
        return writable

    @staticmethod
    def _reserved_stroke_bounds(
        current: RasterBounds,
        requested: RasterBounds,
    ) -> RasterBounds:
        """Amortize interactive growth by reserving one current span per crossed edge."""
        combined = current.united(requested)
        left = (
            min(combined.x, current.x - current.width)
            if requested.x < current.x
            else combined.x
        )
        top = (
            min(combined.y, current.y - current.height)
            if requested.y < current.y
            else combined.y
        )
        right = (
            max(combined.right, current.right + current.width)
            if requested.right > current.right
            else combined.right
        )
        bottom = (
            max(combined.bottom, current.bottom + current.height)
            if requested.bottom > current.bottom
            else combined.bottom
        )
        return RasterBounds(left, top, right - left, bottom - top)

    def prepare_stroke_job(
        self,
        mask_id: uuid.UUID,
        dirty_rect: QRect,
        *,
        payload: MaskStrokePayload | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> MaskStrokeJobSpec | None:
        """Snapshot the data required to process a stroke off the UI thread."""
        layer = self._get_layer(mask_id)
        if layer is None or self._layer_is_empty(layer):
            logger.warning("Cannot prepare stroke job for missing mask %s.", mask_id)
            return None
        surface_bounds = layer.surface.bounds
        if surface_bounds is None:
            return None
        storage_rect = QRect(0, 0, surface_bounds.width, surface_bounds.height)
        bounded = dirty_rect.normalized().intersected(storage_rect)
        if bounded.isNull() or bounded.isEmpty():
            return None
        top = bounded.top()
        left = bounded.left()
        height = bounded.height()
        width = bounded.width()
        before_slice = layer.surface.snapshot_storage_region(
            RasterBounds(left, top, width, height)
        )
        meta: MutableMapping[str, Any]
        if metadata is None:
            meta = {}
        else:
            meta = dict(metadata)
        return MaskStrokeJobSpec(
            mask_id=mask_id,
            generation=self.async_epoch(mask_id),
            dirty_rect=bounded,
            before=before_slice,
            payload=payload,
            metadata=meta,
        )

    def apply_stroke_job(
        self,
        job: MaskStrokeJobResult,
        *,
        emit_mask_updated: bool = True,
        on_stale: Callable[[MaskStrokeJobResult], None] | None = None,
    ) -> bool:
        """Merge a stroke job result into the canonical mask state."""
        mask_id = job.mask_id
        diagnostics_log = (
            logger.info
            if getattr(self._diagnostics, "logging_enabled", False)
            else logger.debug
        )
        layer = self._get_layer(mask_id)
        if layer is None or self._layer_is_empty(layer):
            logger.warning("Cannot apply stroke job for missing mask %s.", mask_id)
            return False
        expected_generation = self.async_epoch(mask_id)
        if job.generation != expected_generation:
            allow_rebase = bool(job.metadata.get("allow_generation_rebase"))
            if allow_rebase and job.generation < expected_generation:
                diagnostics_log(
                    "rebasing stroke job generation (mask=%s job=%s expected=%s)",
                    mask_id,
                    job.generation,
                    expected_generation,
                )
                self._record_stroke_event("rebased")
                job = replace(job, generation=expected_generation)
            elif job.generation > expected_generation:
                diagnostics_log(
                    "clamping future stroke job generation (mask=%s job=%s expected=%s)",
                    mask_id,
                    job.generation,
                    expected_generation,
                )
                self._record_stroke_event("clamped")
                job = replace(job, generation=expected_generation)
            else:
                logger.info(
                    "Discarded stroke job for mask %s due to stale generation (job=%s current=%s).",
                    mask_id,
                    job.generation,
                    expected_generation,
                )
                self._record_stroke_event("stale_drop")
                if on_stale is not None:
                    on_stale(job)
                return False
        rect = job.dirty_rect.normalized()
        if rect.isNull() or rect.isEmpty():
            return False
        height = rect.height()
        width = rect.width()
        if job.after.shape != (height, width) or job.before.shape != (height, width):
            logger.error(
                "Stroke job payload dimensions do not match dirty rect %s for mask %s.",
                rect,
                mask_id,
            )
            return False
        if np.array_equal(job.before, job.after):
            self._record_stroke_event("no_op")
            return True
        top = rect.top()
        left = rect.left()
        bottom = top + height
        right = left + width

        def _apply(dest_view: np.ndarray, _: QImage) -> None:
            """Copy the stroke result into the destination mask slice."""
            region = dest_view[top:bottom, left:right]
            np.copyto(region, job.after)

        layer.surface.mutate(_apply)
        self.record_stroke_patch_from_arrays(
            mask_id,
            rect,
            job.before,
            job.after,
            already_applied=True,
        )
        self.advance_epoch(mask_id, reason="stroke_job_applied")
        self._renders.promote_revision(mask_id)
        if emit_mask_updated:
            self._mask_changed(mask_id, rect)
        return True

    def _array_to_patch_image(self, array: np.ndarray) -> QImage:
        """Return a detached QImage created from a grayscale NumPy array."""
        if array.ndim != 2:
            raise ValueError("Patch arrays must be 2-D grayscale slices.")
        if array.dtype != np.uint8:
            array = array.astype(np.uint8, copy=False)
        return numpy_to_qimage_grayscale8(array)

    def record_stroke_patch(
        self,
        mask_id: uuid.UUID,
        rect: QRect,
        before: QImage,
        after: QImage,
        *,
        already_applied: bool = False,
    ) -> None:
        """Record a patch delta for `mask_id` covering `rect`."""
        before_np = qimage_to_numpy_grayscale8(before)
        after_np = qimage_to_numpy_grayscale8(after)
        self.record_stroke_patch_from_arrays(
            mask_id,
            rect,
            before_np,
            after_np,
            already_applied=already_applied,
        )

    def record_stroke_patch_from_arrays(
        self,
        mask_id: uuid.UUID,
        rect: QRect,
        before: np.ndarray,
        after: np.ndarray,
        *,
        already_applied: bool = False,
    ) -> None:
        """Record a patch delta using precomputed grayscale arrays."""
        if rect.isNull() or rect.isEmpty():
            return
        if before.shape != after.shape:
            raise ValueError("Patch arrays must share identical shape.")
        diff_mask = before != after
        if not np.any(diff_mask):
            return
        ys, xs = np.nonzero(diff_mask)
        min_y = int(ys.min())
        max_y = int(ys.max())
        min_x = int(xs.min())
        max_x = int(xs.max())
        local_width = max_x - min_x + 1
        local_height = max_y - min_y + 1
        normalized_rect = rect.normalized()
        global_top_left = QPoint(
            normalized_rect.left() + min_x,
            normalized_rect.top() + min_y,
        )
        global_rect = QRect(global_top_left, QSize(local_width, local_height))
        before_slice = before[min_y : max_y + 1, min_x : max_x + 1]
        after_slice = after[min_y : max_y + 1, min_x : max_x + 1]
        before_image = self._array_to_patch_image(before_slice)
        after_image = self._array_to_patch_image(after_slice)
        mask_slice = np.ascontiguousarray(
            diff_mask[min_y : max_y + 1, min_x : max_x + 1]
        )
        self._stroke_history.add_patch(
            mask_id,
            MaskPatch(
                rect=global_rect,
                before=before_image,
                after=after_image,
                mask=mask_slice,
            ),
            already_applied=already_applied,
        )

    def _commit_mask_update(
        self,
        mask_id: uuid.UUID,
        *,
        image: QImage | None = None,
        before: QImage | None = None,
        patches: Sequence[MaskPatch] | tuple[MaskPatch, ...] = (),
        preserve_cache: bool = False,
        already_applied: bool = False,
    ) -> bool:
        """Submit the recorded update and refresh caches."""
        layer_before = self._get_layer(mask_id)
        bounds_before = None if layer_before is None else layer_before.surface.bounds
        if patches:
            if already_applied:
                success = self._assets.record_applied_mask_patches(
                    mask_id,
                    patches,
                )
            else:
                success = self._assets.commit_mask_patches(mask_id, patches)
        else:
            if image is None:
                logger.error(
                    "commit_mask_update aborted for mask %s: image payload missing.",
                    mask_id,
                )
                return False
            success = self._assets.commit_mask_image(
                mask_id,
                image,
                before_image=before,
            )
        if not success:
            return False
        if not already_applied:
            self.advance_epoch(mask_id, reason="commit_mask_update")
        layer = self._get_layer(mask_id)
        if layer is not None and not preserve_cache:
            self._renders.invalidate_layer(layer)
        if layer is not None and layer.surface.bounds != bounds_before:
            self._structure_changed()
        self._undo_changed(mask_id)
        return True

    def _apply_history_operation(
        self, operator: Callable[[uuid.UUID], MaskHistoryChange | None]
    ) -> bool:
        """Execute an undo/redo operation supplied by the manager."""
        mask_id = self._active_mask_id()
        if mask_id is None:
            return False
        layer_before = self._get_layer(mask_id)
        bounds_before = None if layer_before is None else layer_before.surface.bounds
        change = operator(mask_id)
        if change is None:
            return False
        mask_layer = self._get_layer(mask_id)
        applied_delta = False
        if mask_layer is not None and change.has_snippets:
            applied_delta = self._renders.apply_history_delta(mask_layer, change)
        if not applied_delta:
            if mask_layer is not None:
                self._renders.invalidate_layer(mask_layer)
            self._mask_changed(mask_id, QRect())
        if mask_layer is not None and mask_layer.surface.bounds != bounds_before:
            self._structure_changed()
        self._undo_changed(mask_id)
        return True

    def undo(self) -> bool:
        """Undo the most recent mask change tracked for the active layer."""
        return self._apply_history_operation(self._assets.undo_mask)

    def redo(self) -> bool:
        """Redo the previously undone mask change for the active layer."""
        return self._apply_history_operation(self._assets.redo_mask)

    def begin_stroke(self):
        """Prepare the patch accumulator for the next undoable stroke."""
        mask_id = self._active_mask_id()
        if mask_id is None:
            return False
        self._stroke_history.begin(mask_id)
        return True

    def update_stroke_image(
        self, mask_id: uuid.UUID, image: QImage
    ) -> MaskLayer | None:
        """Update the mask image without recording an undo command."""
        layer = self._get_layer(mask_id)
        if layer is None:
            logger.warning("Cannot update stroke for missing mask %s.", mask_id)
            return None
        existing_image = layer.mask_image
        bounds_before = layer.surface.bounds
        if not existing_image.isNull() and not image.isNull():
            if existing_image.size() == image.size():
                before_np = qimage_to_numpy_grayscale8(existing_image)
                after_np = qimage_to_numpy_grayscale8(image)
                diff_mask = before_np != after_np
                if np.any(diff_mask):
                    ys, xs = np.nonzero(diff_mask)
                    min_x = int(xs.min())
                    max_x = int(xs.max())
                    min_y = int(ys.min())
                    max_y = int(ys.max())
                    diff_rect = QRect(
                        min_x,
                        min_y,
                        max_x - min_x + 1,
                        max_y - min_y + 1,
                    )
                    before_patch = existing_image.copy(diff_rect)
                    after_patch = image.copy(diff_rect)
                    self.record_stroke_patch(
                        mask_id,
                        diff_rect,
                        before_patch,
                        after_patch,
                        already_applied=True,
                    )
            else:
                logger.debug(
                    "Skipping patch capture for mask %s: stroke image size changed %sx%s -> %sx%s.",
                    mask_id,
                    existing_image.width(),
                    existing_image.height(),
                    image.width(),
                    image.height(),
                )
        self._assets.set_mask_image(mask_id, image)
        self.advance_epoch(mask_id, reason="update_stroke_image")
        if layer.surface.bounds != bounds_before:
            self._structure_changed()
        return layer

    def commit_stroke(self, mask_id: uuid.UUID) -> bool:
        """Finalize a stroke only when it accumulated an actual mask mutation."""
        if self._get_layer(mask_id) is None:
            self._stroke_history.discard(mask_id)
            logger.warning("Cannot commit stroke %s: missing mask.", mask_id)
            return False
        payload = self._stroke_history.consume(mask_id)
        if payload.structural_before is not None:
            layer = self._get_layer(mask_id)
            if layer is None:
                return False
            changed = self._assets.record_applied_surface(
                mask_id,
                payload.structural_before,
                layer.surface.snapshot(),
            )
            if changed:
                self._undo_changed(mask_id)
            return changed
        patches = payload.patches
        already_applied = payload.already_applied
        if patches:
            return self._commit_mask_update(
                mask_id,
                patches=patches,
                preserve_cache=True,
                already_applied=already_applied,
            )
        return False

    def apply_mask_image(
        self,
        mask_id: uuid.UUID,
        image: QImage,
        *,
        before: QImage | None = None,
        preserve_cache: bool = False,
    ) -> bool:
        """Submit an undoable command using patch data when available."""
        payload = self._stroke_history.consume(mask_id)
        patches = payload.patches
        already_applied = payload.already_applied
        if patches:
            return self._commit_mask_update(
                mask_id,
                patches=patches,
                preserve_cache=True,
                already_applied=already_applied,
            )
        return self._commit_mask_update(
            mask_id,
            image=image,
            before=before,
            preserve_cache=preserve_cache,
        )

    def apply_mask_surface(
        self,
        mask_id: uuid.UUID,
        snapshot: MaskSurfaceSnapshot,
    ) -> bool:
        """Commit one complete policy-aware surface edit and invalidate geometry."""
        layer_before = self._get_layer(mask_id)
        bounds_before = None if layer_before is None else layer_before.surface.bounds
        if not self._assets.commit_mask_surface(mask_id, snapshot):
            return False
        self.advance_epoch(mask_id, reason="mask_surface_applied")
        layer = self._get_layer(mask_id)
        if layer is not None:
            self._renders.invalidate_layer(layer)
        if layer is not None and layer.surface.bounds != bounds_before:
            self._structure_changed()
        self._undo_changed(mask_id)
        self._mask_changed(mask_id, QRect())
        return True
