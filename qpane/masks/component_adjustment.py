#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Reusable connected-component adjustment for mask editing tools."""

from __future__ import annotations

import logging
import uuid
from typing import Protocol

import numpy as np
from PySide6.QtCore import QPoint
from PySide6.QtGui import QImage

from .image_ops import adjust_connected_component

logger = logging.getLogger(__name__)


class MaskPixelSource(Protocol):
    """Read mask pixels without depending on a particular UI tool."""

    def get_mask_image_as_numpy(self, mask_id: uuid.UUID) -> np.ndarray | None:
        """Return a detached grayscale array for ``mask_id``."""
        ...


class MaskComponentAdjustmentTool:
    """Grow or shrink the connected mask component under a point."""

    def __init__(self, pixels: MaskPixelSource) -> None:
        """Bind the mask pixel source used by component edits."""
        self._pixels = pixels

    def adjusted_image(
        self,
        mask_id: uuid.UUID,
        point: QPoint,
        *,
        grow: bool,
    ) -> QImage | None:
        """Return adjusted pixels without committing them to mask storage."""
        current = self._pixels.get_mask_image_as_numpy(mask_id)
        if current is None or current.size == 0:
            logger.warning("Cannot adjust mask %s: no mask data available.", mask_id)
            return None
        height, width = current.shape
        x = int(point.x())
        y = int(point.y())
        if x < 0 or y < 0 or x >= width or y >= height:
            logger.warning(
                "Ignoring component adjustment at (%s, %s): outside mask bounds %sx%s for mask %s.",
                x,
                y,
                width,
                height,
                mask_id,
            )
            return None
        adjusted = adjust_connected_component(current, x=x, y=y, grow=grow)
        return None if adjusted is None else _numpy_to_qimage(adjusted)


def _numpy_to_qimage(array: np.ndarray) -> QImage:
    """Convert one contiguous grayscale array into a detached QImage."""
    contiguous = np.ascontiguousarray(array, dtype=np.uint8)
    height, width = contiguous.shape
    return QImage(
        contiguous.data,
        width,
        height,
        int(contiguous.strides[0]),
        QImage.Format_Grayscale8,
    ).copy()
