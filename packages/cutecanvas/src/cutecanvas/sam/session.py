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

"""Own native predictor objects on one stable execution affinity lane."""

from __future__ import annotations

import uuid
from collections import OrderedDict
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtGui import QImage

from qpane.sdk.execution import CancellationToken

from . import service
from .products import (
    SamCacheMutationProduct,
    SamMaskProduct,
    SamPredictorReference,
    SamPreparationProduct,
    SamSessionSnapshot,
)

if TYPE_CHECKING:
    from mobile_sam import SamPredictor


class SamNativeSession:
    """Keep model construction, inference, and destruction on one thread."""

    def __init__(
        self,
        *,
        checkpoint_path: Path,
        device: str,
        cache_limit: int,
    ) -> None:
        """Capture immutable native configuration and cache policy."""
        self._checkpoint_path = Path(checkpoint_path)
        self._device = str(device)
        self._cache_limit = max(0, int(cache_limit))
        self._predictors: OrderedDict[uuid.UUID, SamPredictor] = OrderedDict()
        self._sizes: dict[uuid.UUID, int] = {}

    def prepare(
        self,
        image: QImage,
        image_id: uuid.UUID,
        cancellation: CancellationToken,
    ) -> SamPreparationProduct:
        """Prepare or reuse one predictor entirely on the affinity thread."""
        cancellation.raise_if_cancelled()
        predictor = self._predictors.get(image_id)
        cache_hit = predictor is not None
        if predictor is None:
            predictor = service.load_predictor(
                self._checkpoint_path,
                device=self._device,
            )
            cancellation.raise_if_cancelled()
            if not image.isNull():
                service.set_predictor_image(predictor, prepare_image_rgb(image))
            cancellation.raise_if_cancelled()
            self._predictors[image_id] = predictor
            self._sizes[image_id] = measure_predictor_bytes(predictor)
        else:
            self._predictors.move_to_end(image_id)
        evicted = self._enforce_limit()
        return SamPreparationProduct(
            reference=SamPredictorReference(image_id),
            cache_hit=cache_hit,
            snapshot=self.snapshot(),
            evicted_ids=evicted,
        )

    def predict(
        self,
        image_id: uuid.UUID,
        bbox: np.ndarray,
        erase_mode: bool,
        cancellation: CancellationToken,
    ) -> SamMaskProduct:
        """Run one box inference against a prepared predictor."""
        cancellation.raise_if_cancelled()
        predictor = self._predictors.get(image_id)
        if predictor is None:
            return SamMaskProduct(image_id, bbox.copy(), erase_mode, None)
        self._predictors.move_to_end(image_id)
        mask = service.predict_mask_from_box(predictor, bbox)
        cancellation.raise_if_cancelled()
        normalized = None if mask is None else mask.astype(np.uint8) * 255
        return SamMaskProduct(image_id, bbox.copy(), erase_mode, normalized)

    def remove(
        self,
        image_id: uuid.UUID,
        cancellation: CancellationToken,
    ) -> SamCacheMutationProduct:
        """Destroy one predictor on the affinity thread."""
        cancellation.raise_if_cancelled()
        removed = self._predictors.pop(image_id, None)
        self._sizes.pop(image_id, None)
        removed_ids = () if removed is None else (image_id,)
        del removed
        return SamCacheMutationProduct(removed_ids, self.snapshot())

    def clear(self) -> SamCacheMutationProduct:
        """Destroy every predictor on the affinity thread."""
        removed_ids = tuple(self._predictors)
        self._predictors.clear()
        self._sizes.clear()
        return SamCacheMutationProduct(removed_ids, self.snapshot())

    def set_cache_limit(
        self,
        limit: int,
        cancellation: CancellationToken,
    ) -> SamCacheMutationProduct:
        """Apply cache policy and destroy evicted predictors."""
        cancellation.raise_if_cancelled()
        self._cache_limit = max(0, int(limit))
        removed_ids = self._enforce_limit()
        return SamCacheMutationProduct(removed_ids, self.snapshot())

    def snapshot(self) -> SamSessionSnapshot:
        """Return detached cache metadata in recency order."""
        return SamSessionSnapshot(
            tuple(
                (image_id, self._sizes.get(image_id, 0))
                for image_id in self._predictors
            )
        )

    def _enforce_limit(self) -> tuple[uuid.UUID, ...]:
        """Destroy least-recently-used predictors beyond the current limit."""
        removed: list[uuid.UUID] = []
        while len(self._predictors) > self._cache_limit:
            image_id, predictor = self._predictors.popitem(last=False)
            self._sizes.pop(image_id, None)
            removed.append(image_id)
            del predictor
        return tuple(removed)


def prepare_image_rgb(image: QImage) -> np.ndarray:
    """Convert a QImage to the contiguous RGB layout expected by the model."""
    working = (
        image
        if image.format() == QImage.Format_RGBA8888
        else image.convertToFormat(QImage.Format_RGBA8888)
    )
    height = working.height()
    width = working.width()
    bytes_per_line = working.bytesPerLine()
    raw = np.frombuffer(
        working.constBits(),
        dtype=np.uint8,
        count=height * bytes_per_line,
    ).reshape((height, bytes_per_line))
    return raw[:, : width * 4].reshape((height, width, 4))[:, :, :3].copy()


def measure_predictor_bytes(predictor: object) -> int:
    """Measure parameter and buffer storage owned by one predictor."""
    model = getattr(predictor, "model", None)
    if model is None:
        return 0

    def _sum_bytes(tensors: Iterable[object]) -> int:
        """Sum tensor storage while tolerating optional model wrappers."""
        total = 0
        for tensor in tensors:
            try:
                total += int(tensor.numel()) * int(tensor.element_size())
            except (RuntimeError, TypeError, ValueError, OverflowError, AttributeError):
                continue
        return total

    return _sum_bytes(getattr(model, "parameters", lambda: ())()) + _sum_bytes(
        getattr(model, "buffers", lambda: ())()
    )


__all__ = [
    "SamNativeSession",
    "measure_predictor_bytes",
    "prepare_image_rgb",
]
