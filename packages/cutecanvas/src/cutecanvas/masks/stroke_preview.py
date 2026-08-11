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
"""Incremental, selection-constrained preview state for one mask stroke."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from uuid import UUID

import numpy as np
from PySide6.QtCore import QRect
from PySide6.QtGui import QImage, QPainter
from qpane.sdk.raster import (
    numpy_to_qimage_grayscale8,
    qimage_to_numpy_grayscale8,
)

from ..coverage.spatial_constraint import CoverageSpatialConstraint
from ..painting import BrushCompositor, BrushDab, BrushDabEngine, BrushStrokeSegment
from ..painting.qt_dab_painter import paint_coverage_segments
from ..painting.rendering import apply_coverage_constraint
from .mask_controller import MaskController
from .stroke_models import (
    MaskStrokeJobSpec,
    MaskStrokePayload,
)

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
    compositor: BrushCompositor = field(default_factory=BrushCompositor)
    constraint: CoverageSpatialConstraint | None = None
    constraint_region: Callable[[QRect, int], np.ndarray] | None = None
    _segments: list[BrushStrokeSegment] = field(default_factory=list)
    _segment_rects: list[QRect] = field(default_factory=list)
    _dirty_rect: QRect | None = None

    def reset(self) -> None:
        """Clear recorded segments and tracked dirty bounds."""
        self._segments.clear()
        self._segment_rects.clear()
        self._dirty_rect = None

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
        for rect in self._segment_rects:
            rect.translate(delta_x, delta_y)
        if self._dirty_rect is not None:
            self._dirty_rect.translate(delta_x, delta_y)

    def preview_segment(
        self,
        *,
        dirty_rect: QRect,
        segment: BrushStrokeSegment,
        snapshot_region: Callable[[QRect, int], np.ndarray],
        render_accumulated: bool = False,
    ) -> MaskStrokePreview:
        """Record a segment and render only its affected provisional patch."""
        self._segments.append(segment)
        self._segment_rects.append(QRect(dirty_rect))
        previous_rect = None if self._dirty_rect is None else QRect(self._dirty_rect)
        combined = (
            QRect(dirty_rect)
            if previous_rect is None
            else previous_rect.united(dirty_rect)
        )
        self._dirty_rect = self._aligned_preview_rect(combined)
        return self._render_preview(
            (
                QRect(self._dirty_rect)
                if render_accumulated
                else self._aligned_preview_rect(dirty_rect)
            ),
            snapshot_region,
        )

    def current_preview(
        self,
        snapshot_region: Callable[[QRect, int], np.ndarray],
    ) -> MaskStrokePreview | None:
        """Render all recorded segments against the latest durable mask pixels."""
        if not self._segments or self._dirty_rect is None:
            return None
        return self._render_preview(QRect(self._dirty_rect), snapshot_region)

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

    def _render_preview(
        self,
        rect: QRect,
        snapshot_region: Callable[[QRect, int], np.ndarray],
    ) -> MaskStrokePreview:
        """Render relevant recorded segments into one durable-backed patch."""
        stride = max(1, self.stride)
        before = snapshot_region(rect, stride)
        image = numpy_to_qimage_grayscale8(before)
        segments = tuple(
            segment
            for segment, segment_rect in zip(
                self._segments,
                self._segment_rects,
                strict=True,
            )
            if segment_rect.intersects(rect)
        )
        self._paint_preview_segments(image, rect, segments)
        constraint_region = self.constraint_region
        if constraint_region is not None:
            painted = qimage_to_numpy_grayscale8(image)
            constraint = constraint_region(rect, stride)
            image = numpy_to_qimage_grayscale8(
                apply_coverage_constraint(before, painted, constraint)
            )
        image.setText("qpane_preview_stride", str(stride))
        image.setText("qpane_preview_provisional", "1")
        return MaskStrokePreview(rect=QRect(rect), image=image)

    def _aligned_preview_rect(self, rect: QRect) -> QRect:
        """Keep preview sampling anchored to the storage origin as bounds grow."""
        stride = max(1, self.stride)
        left = rect.left() - rect.left() % stride
        top = rect.top() - rect.top() % stride
        return QRect(left, top, rect.right() - left + 1, rect.bottom() - top + 1)

    def _paint_preview_segments(
        self,
        preview: QImage,
        dirty_rect: QRect,
        segments: tuple[BrushStrokeSegment, ...] | list[BrushStrokeSegment],
    ) -> None:
        """Paint only the supplied semantic segments into the cached preview."""
        if any(segment.texture_strength > 0.0 for segment in segments):
            self._paint_textured_preview(preview, dirty_rect, segments)
            return
        paint_coverage_segments(
            preview,
            dirty_rect.topLeft(),
            tuple(segments),
            stride=max(1, self.stride),
        )

    def _paint_textured_preview(
        self,
        preview: QImage,
        dirty_rect: QRect,
        segments: tuple[BrushStrokeSegment, ...] | list[BrushStrokeSegment],
    ) -> None:
        """Composite cached textured tips in preview-local coordinates."""
        stride = max(1, self.stride)
        pixels = qimage_to_numpy_grayscale8(preview)
        engine = BrushDabEngine()
        patch_bounds = QRect(0, 0, preview.width(), preview.height())
        for segment in segments:
            dabs = tuple(
                BrushDab(
                    center=(
                        (dab.center[0] - dirty_rect.left()) / stride,
                        (dab.center[1] - dirty_rect.top()) / stride,
                    ),
                    diameter=max(1.0, dab.diameter / stride),
                    hardness=dab.hardness,
                    opacity=dab.opacity,
                    angle=dab.angle,
                    texture_strength=dab.texture_strength,
                    texture_scale=max(0.25, dab.texture_scale / stride),
                    texture_seed=dab.texture_seed,
                    tip_transform=dab.tip_transform,
                )
                for dab in engine.segment_dabs(segment)
            )
            pixels = self.compositor.render_coverage_dabs(
                before=pixels,
                patch_bounds=patch_bounds,
                dabs=dabs,
                operation=segment.operation,
            )
        updated = numpy_to_qimage_grayscale8(pixels)
        painter = QPainter(preview)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.drawImage(0, 0, updated)
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
