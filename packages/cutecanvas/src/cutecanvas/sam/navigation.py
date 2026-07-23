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
"""Adapt SAM predictor preparation to QPane's navigation warmup contract."""

from __future__ import annotations

import uuid
from pathlib import Path

from PySide6.QtGui import QImage

from .manager import SamManager


class SamNavigationWarmup:
    """Own the SAM-specific implementation of source warmup operations."""

    def __init__(self, manager: SamManager) -> None:
        """Store the predictor manager used by navigation requests."""
        self._manager = manager

    def request(
        self,
        image: QImage,
        image_id: uuid.UUID,
        *,
        source_path: Path | None = None,
    ) -> None:
        """Request a predictor for one catalog source."""
        self._manager.requestPredictor(image, image_id, source_path=source_path)

    def cancel(self, image_id: uuid.UUID) -> bool:
        """Cancel an inflight predictor request when possible."""
        return self._manager.cancelPendingPredictor(image_id)

    def invalidate(self, image_id: uuid.UUID) -> None:
        """Remove a predictor derived from changed source pixels."""
        self._manager.removeFromCache(image_id)
