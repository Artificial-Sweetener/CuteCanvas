#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Incremental, selection-constrained preview state for one mask stroke."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from uuid import UUID

import numpy as np
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QImage, QPainter

from ..coverage import CoverageSnapshot
from ..raster.image_conversion import (
    numpy_to_qimage_grayscale8,
    qimage_to_numpy_grayscale8,
)
from .mask_controller import MaskController
from .stroke_models import (
    MaskStrokeJobSpec,
    MaskStrokePayload,
    MaskStrokeSegmentPayload,
)
from .stroke_render import apply_coverage_constraint, paint_stroke_segment

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MaskStrokePreview:
    """Bind a provisional mask image to its image-space destination rectangle."""

    rect: QRect
    image: QImage


@dataclass(slots=True)
class DecimatedStrokePreview:
    """Own one in-flight stroke rendered against a stride-reduced preview."""

    mask_id: UUID
    stride: int
    constraint: CoverageSnapshot | None = None
    constraint_region: Callable[[QRect, int], np.ndarray] | None = None
    _segments: list[MaskStrokeSegmentPayload] = field(default_factory=list)
    _dirty_rect: QRect | None = None
    _preview_image: QImage | None = None

    def reset(self) -> None:
        """Clear recorded segments and tracked dirty bounds."""
        self._segments.clear()
        self._dirty_rect = None
        self._preview_image = None

    def has_segments(self) -> bool:
        """Return True when the stroke has recorded paint operations."""
        return bool(self._segments)

    def dirty_rect(self) -> QRect | None:
        """Return a defensive copy of the provisional image-space bounds."""
        return None if self._dirty_rect is None else QRect(self._dirty_rect)

    def translate_storage(self, delta_x: int, delta_y: int) -> None:
        """Rebase provisional storage coordinates after left/top expansion."""
        if delta_x == 0 and delta_y == 0:
            return
        self._segments = [
            segment.translated(float(delta_x), float(delta_y))
            for segment in self._segments
        ]
        if self._dirty_rect is not None:
            self._dirty_rect.translate(delta_x, delta_y)
        self._preview_image = None

    def preview_segment(
        self,
        *,
        dirty_rect: QRect,
        segment: MaskStrokeSegmentPayload,
        snapshot_region: Callable[[QRect, int], np.ndarray],
    ) -> MaskStrokePreview:
        """Record a segment and render its accumulated provisional mask."""
        self._segments.append(segment)
        previous_rect = None if self._dirty_rect is None else QRect(self._dirty_rect)
        combined = (
            QRect(dirty_rect)
            if previous_rect is None
            else previous_rect.united(dirty_rect)
        )
        self._dirty_rect = self._aligned_preview_rect(combined)
        if self.constraint_region is not None:
            self._preview_image = None
            self._render_constrained_preview(snapshot_region)
            preview = self.current_preview(snapshot_region)
            if preview is None:
                raise RuntimeError("recorded stroke must produce a preview image")
            return preview
        previous_image = self._preview_image
        rebuild = previous_image is None
        if rebuild or previous_rect != self._dirty_rect:
            preview_slice = snapshot_region(self._dirty_rect, max(1, self.stride))
            self._preview_image = numpy_to_qimage_grayscale8(preview_slice)
            if previous_image is not None and previous_rect is not None:
                self._copy_previous_preview(previous_image, previous_rect)
        self._paint_preview_segments(self._segments if rebuild else (segment,))
        preview = self.current_preview(snapshot_region)
        if preview is None:
            raise RuntimeError("recorded stroke must produce a preview image")
        return preview

    def current_preview(
        self,
        snapshot_region: Callable[[QRect, int], np.ndarray],
    ) -> MaskStrokePreview | None:
        """Render all recorded segments against the latest durable mask pixels."""
        if not self._segments or self._dirty_rect is None:
            return None
        rect_copy = QRect(self._dirty_rect)
        stride = max(1, self.stride)
        if self._preview_image is None:
            if self.constraint_region is None:
                preview_slice = snapshot_region(rect_copy, stride)
                self._preview_image = numpy_to_qimage_grayscale8(preview_slice)
                self._paint_preview_segments(self._segments)
            else:
                self._render_constrained_preview(snapshot_region)
        preview_image = self._preview_image
        preview_image.setText("qpane_preview_stride", str(stride))
        preview_image.setText("qpane_preview_provisional", "1")
        return MaskStrokePreview(rect=rect_copy, image=preview_image)

    def flush_to_mask(
        self,
        *,
        controller: MaskController,
        submit_job: Callable[[MaskStrokeJobSpec, str, bool, int], bool],
        source: str,
        commit: bool,
        allocate_job_token: Callable[[], int],
        register_job_token: Callable[[UUID, int], int | None],
        restore_job_token: Callable[[UUID, int | None], None],
    ) -> bool:
        """Ship recorded segments to a worker for final application."""
        if not self._segments or self._dirty_rect is None:
            self.reset()
            return False
        rect = QRect(self._dirty_rect)
        payload = self._build_payload()
        spec = controller.edits.prepare_stroke_job(
            self.mask_id,
            rect,
            payload=payload,
            metadata=dict(payload.metadata),
            constraint=(
                None
                if self.constraint_region is None
                else self.constraint_region(rect, 1)
            ),
        )
        if spec is None:
            self.reset()
            return False
        job_token = allocate_job_token()
        metadata = dict(spec.metadata)
        metadata["job_token"] = job_token
        previous_token = register_job_token(self.mask_id, job_token)
        if previous_token is not None:
            metadata["allow_generation_rebase"] = True
        spec_with_token = replace(spec, metadata=metadata)
        logger.debug(
            "prepared stroke job mask=%s gen=%s commit=%s source=%s token=%s",
            spec_with_token.mask_id,
            spec_with_token.generation,
            commit,
            source,
            job_token,
        )
        try:
            queued = submit_job(
                spec_with_token,
                source=source,
                commit=commit,
                job_token=job_token,
            )
        except Exception:
            restore_job_token(self.mask_id, previous_token)
            self.reset()
            raise
        if not queued:
            restore_job_token(self.mask_id, previous_token)
        self.reset()
        return queued

    def _render_constrained_preview(
        self,
        snapshot_region: Callable[[QRect, int], np.ndarray],
    ) -> None:
        """Rebuild accumulated preview once through immutable selection coverage."""
        dirty_rect = self._dirty_rect
        constraint_region = self.constraint_region
        if dirty_rect is None or constraint_region is None:
            return
        stride = max(1, self.stride)
        before = snapshot_region(dirty_rect, stride)
        self._preview_image = numpy_to_qimage_grayscale8(before)
        self._paint_preview_segments(self._segments)
        preview = self._preview_image
        if preview is None:
            return
        painted = qimage_to_numpy_grayscale8(preview)
        constraint = constraint_region(dirty_rect, stride)
        self._preview_image = numpy_to_qimage_grayscale8(
            apply_coverage_constraint(before, painted, constraint)
        )

    def _aligned_preview_rect(self, rect: QRect) -> QRect:
        """Keep preview sampling anchored to the storage origin as bounds grow."""
        stride = max(1, self.stride)
        left = rect.left() - rect.left() % stride
        top = rect.top() - rect.top() % stride
        return QRect(left, top, rect.right() - left + 1, rect.bottom() - top + 1)

    def _copy_previous_preview(self, image: QImage, rect: QRect) -> None:
        """Overlay the prior provisional pixels into an enlarged preview image."""
        preview = self._preview_image
        dirty_rect = self._dirty_rect
        if preview is None or dirty_rect is None:
            return
        stride = max(1, self.stride)
        painter = QPainter(preview)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.drawImage(
            QPoint(
                (rect.left() - dirty_rect.left()) // stride,
                (rect.top() - dirty_rect.top()) // stride,
            ),
            image,
        )
        painter.end()

    def _paint_preview_segments(
        self,
        segments: tuple[MaskStrokeSegmentPayload, ...] | list[MaskStrokeSegmentPayload],
    ) -> None:
        """Paint only the supplied semantic segments into the cached preview."""
        preview = self._preview_image
        dirty_rect = self._dirty_rect
        if preview is None or dirty_rect is None:
            return
        painter = QPainter(preview)
        try:
            for segment in segments:
                paint_stroke_segment(
                    painter,
                    dirty_rect.topLeft(),
                    segment,
                    stride=max(1, self.stride),
                )
        finally:
            painter.end()

    def _build_payload(self) -> MaskStrokePayload:
        """Return the recorded segments packaged for worker execution."""
        segments = tuple(self._segments)
        metadata = {"segment_count": len(segments), "stride": self.stride}
        metadata["source"] = "decimated" if self.stride > 1 else "direct"
        return MaskStrokePayload(
            segments=segments,
            stride=self.stride,
            metadata=metadata,
        )
