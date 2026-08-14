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
"""Build detached derived mask-render products."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from time import monotonic

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage

from qpane.sdk.execution import CancellationToken

from .mask import MaskAssetStore
from .mask_controller import MaskController
from .resampled_products import resample_mask_overlay


@dataclass(frozen=True, slots=True)
class PrefetchedOverlay:
    """Carry one colorized overlay and optional scaled derivatives."""

    mask_id: uuid.UUID
    render_revision: int
    image: QImage
    scaled: tuple[tuple[float, QImage], ...] = ()
    colorize_duration_ms: float | None = None


@dataclass(frozen=True, slots=True)
class MaskPrefetchProduct:
    """Carry all detached products from one composition prefetch."""

    image_id: uuid.UUID
    warmed: tuple[PrefetchedOverlay, ...]
    failures: tuple[tuple[uuid.UUID, str], ...]
    duration_ms: float


@dataclass(frozen=True, slots=True)
class MaskSnippetProduct:
    """Carry one detached colorized dirty mask region."""

    mask_id: uuid.UUID
    render_revision: int
    dirty_rect: QRect
    image: QImage
    colorize_duration_ms: float


def build_mask_prefetch(
    *,
    image_id: uuid.UUID,
    mask_ids: Sequence[uuid.UUID],
    assets: MaskAssetStore,
    controller: MaskController,
    current_mask_id: uuid.UUID | None,
    scales: Sequence[float],
    cancellation: CancellationToken,
) -> MaskPrefetchProduct:
    """Build colorized base and scaled mask overlays cooperatively."""
    ordered = list(mask_ids)
    if current_mask_id in ordered:
        ordered.remove(current_mask_id)
        ordered.insert(0, current_mask_id)
    warmed: list[PrefetchedOverlay] = []
    failures: list[tuple[uuid.UUID, str]] = []
    started = monotonic()
    for mask_id in ordered:
        cancellation.raise_if_cancelled()
        layer = assets.get_layer(mask_id)
        if layer is None or layer.coverage.raster.is_null():
            continue
        render_revision = controller.renders.render_revision(mask_id)
        try:
            colorize_started = monotonic()
            image = controller.renders.prepare_image_detached(layer, mask_id=mask_id)
            colorize_duration_ms = (monotonic() - colorize_started) * 1000.0
        except Exception as exc:  # noqa: BLE001 - isolate one invalid mask
            failures.append((mask_id, str(exc)))
            continue
        if image is None:
            continue
        scaled_outputs: list[tuple[float, QImage]] = []
        for scale_key in scales:
            cancellation.raise_if_cancelled()
            target_size = controller.renders.target_scaled_size(
                image.size(),
                scale_key,
            )
            if target_size == image.size() or target_size.isEmpty():
                continue
            scaled_image = resample_mask_overlay(
                image,
                target_size,
                cancellation,
            )
            if not scaled_image.isNull():
                scaled_outputs.append((scale_key, scaled_image))
        warmed.append(
            PrefetchedOverlay(
                mask_id,
                render_revision,
                image,
                tuple(scaled_outputs),
                colorize_duration_ms,
            )
        )
    return MaskPrefetchProduct(
        image_id,
        tuple(warmed),
        tuple(failures),
        (monotonic() - started) * 1000.0,
    )


def build_mask_snippet(
    *,
    mask_id: uuid.UUID,
    render_revision: int,
    dirty_rect: QRect,
    snippet: QImage,
    color: QColor,
    controller: MaskController,
    cancellation: CancellationToken,
) -> MaskSnippetProduct:
    """Colorize one detached dirty mask region cooperatively."""
    cancellation.raise_if_cancelled()
    started = monotonic()
    image = controller.renders.rasterize_detached(snippet, color)
    duration_ms = (monotonic() - started) * 1000.0
    cancellation.raise_if_cancelled()
    return MaskSnippetProduct(
        mask_id,
        render_revision,
        QRect(dirty_rect),
        image,
        duration_ms,
    )
