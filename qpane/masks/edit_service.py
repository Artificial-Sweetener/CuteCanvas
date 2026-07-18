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
from dataclasses import dataclass, replace
from typing import Any

import numpy as np
from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QImage

from ..catalog.image_utils import (
    numpy_to_qimage_grayscale8,
    qimage_to_numpy_grayscale8,
)
from .combiner import MaskCombiner
from .mask import MaskAssetStore, MaskLayer
from .mask_diagnostics import MaskStrokeDiagnostics
from .mask_undo import MaskHistoryChange, MaskPatch
from .render_cache import MaskRenderCache
from .stroke_models import MaskStrokeJobResult, MaskStrokeJobSpec, MaskStrokePayload

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MaskReadyUpdate:
    """Describe a generated mask update awaiting overlay promotion."""

    mask_id: uuid.UUID
    dirty_rect: QRect | None
    mask_layer: MaskLayer | None
    changed: bool


@dataclass(slots=True)
class _StrokeAccumulator:
    """Collect and merge mask patches produced during a stroke."""

    _patches: list[MaskPatch]
    _already_applied: bool | None

    def __init__(self) -> None:
        """Start with an empty patch list ready to capture strokes."""
        self._patches = []
        self._already_applied = None

    def reset(self) -> None:
        """Clear the recorded patches so a new stroke can begin."""
        self._patches.clear()
        self._already_applied = None

    def add_patch(self, patch: MaskPatch, *, already_applied: bool) -> None:
        """Append one patch while preserving application semantics."""
        if (
            self._already_applied is not None
            and self._already_applied != already_applied
        ):
            raise ValueError("A stroke cannot mix applied and unapplied mask patches.")
        self._already_applied = already_applied
        self._patches.append(patch)

    def consume(self) -> tuple[tuple[MaskPatch, ...], bool]:
        """Return and clear the recorded patches."""
        patches = tuple(self._patches)
        already_applied = bool(self._already_applied)
        self.reset()
        return patches, already_applied


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
        diagnostics: MaskStrokeDiagnostics | None = None,
    ) -> None:
        """Initialize editing with explicit state-owner collaborators."""
        self._assets = assets
        self._combiner = MaskCombiner(assets)
        self._renders = renders
        self._epochs = epochs
        self._active_mask_id = active_mask_id
        self._mask_changed = mask_changed
        self._undo_changed = undo_changed
        self._diagnostics = diagnostics
        self._stroke_accumulators: dict[uuid.UUID, _StrokeAccumulator] = {}

    def _get_layer(self, mask_id: uuid.UUID | None) -> MaskLayer | None:
        """Return the canonical layer for a source id."""
        return None if mask_id is None else self._assets.get_layer(mask_id)

    @staticmethod
    def _layer_is_empty(layer: MaskLayer | None) -> bool:
        """Return whether a layer lacks canonical pixels."""
        return layer is None or layer.mask_image.isNull()

    def _record_stroke_event(self, event: str) -> None:
        """Record edit diagnostics when configured."""
        if self._diagnostics is not None and event:
            self._diagnostics.record_generation_event(event)

    def _ensure_stroke_accumulator(self, mask_id: uuid.UUID) -> _StrokeAccumulator:
        """Return the accumulator for `mask_id`, creating it when missing."""
        accumulator = self._stroke_accumulators.get(mask_id)
        if accumulator is None:
            accumulator = _StrokeAccumulator()
            self._stroke_accumulators[mask_id] = accumulator
        return accumulator

    def _drain_stroke_patches(
        self, mask_id: uuid.UUID
    ) -> tuple[tuple[MaskPatch, ...], bool]:
        """Return and clear recorded patches for ``mask_id``."""
        accumulator = self._stroke_accumulators.pop(mask_id, None)
        if accumulator is None:
            return (), False
        return accumulator.consume()

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
        self._renders.discard_source(mask_id)

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
        bounded = dirty_rect.normalized().intersected(layer.mask_image.rect())
        if bounded.isNull() or bounded.isEmpty():
            return None
        top = bounded.top()
        left = bounded.left()
        height = bounded.height()
        width = bounded.width()
        bottom = top + height
        right = left + width
        view = layer.surface.snapshot_array()
        before_slice = np.array(view[top:bottom, left:right], copy=True)
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
        accumulator = self._ensure_stroke_accumulator(mask_id)
        accumulator.add_patch(
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
        self._undo_changed(mask_id)
        return True

    def _apply_history_operation(
        self, operator: Callable[[uuid.UUID], MaskHistoryChange | None]
    ) -> bool:
        """Execute an undo/redo operation supplied by the manager."""
        mask_id = self._active_mask_id()
        if mask_id is None:
            return False
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
        accumulator = self._ensure_stroke_accumulator(mask_id)
        accumulator.reset()
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
        return layer

    def commit_stroke(self, mask_id: uuid.UUID) -> bool:
        """Finalize a stroke only when it accumulated an actual mask mutation."""
        if self._get_layer(mask_id) is None:
            self._stroke_accumulators.pop(mask_id, None)
            logger.warning("Cannot commit stroke %s: missing mask.", mask_id)
            return False
        patches, already_applied = self._drain_stroke_patches(mask_id)
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
        patches, already_applied = self._drain_stroke_patches(mask_id)
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

    def apply_generated_mask(
        self,
        mask_array_uint8: np.ndarray | None,
        bbox: np.ndarray,
        erase_mode: bool,
    ) -> MaskReadyUpdate | None:
        """Process a generated mask from SAM and describe the resulting change."""
        mask_id = self._active_mask_id()
        if mask_id is None:
            return None
        mask_layer = self._get_layer(mask_id)
        if mask_array_uint8 is None:
            self._renders.invalidate(mask_id)
            image_rect = QRect(
                QPoint(int(bbox[0]), int(bbox[1])),
                QPoint(int(bbox[2]), int(bbox[3])),
            )
            return MaskReadyUpdate(
                mask_id=mask_id,
                dirty_rect=image_rect,
                mask_layer=mask_layer,
                changed=False,
            )
        new_image = self._combiner.combine(
            mask_id,
            mask_array_uint8,
            erase_mode=erase_mode,
        )
        if new_image is None:
            return MaskReadyUpdate(
                mask_id=mask_id,
                dirty_rect=None,
                mask_layer=mask_layer,
                changed=False,
            )
        if not self.apply_mask_image(
            mask_id,
            new_image,
            preserve_cache=True,
        ):
            return MaskReadyUpdate(
                mask_id=mask_id,
                dirty_rect=None,
                mask_layer=mask_layer,
                changed=False,
            )
        mask_layer = self._get_layer(mask_id)
        image_rect = QRect(
            QPoint(int(bbox[0]), int(bbox[1])),
            QPoint(int(bbox[2]), int(bbox[3])),
        )
        return MaskReadyUpdate(
            mask_id=mask_id,
            dirty_rect=image_rect,
            mask_layer=mask_layer,
            changed=True,
        )
