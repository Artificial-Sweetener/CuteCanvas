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

"""Own admission policy and rejection diagnostics for mask render products."""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtGui import QImage

logger = logging.getLogger(__name__)


class MaskRenderAdmission:
    """Decide and diagnose optional retention for derived mask rasters."""

    def __init__(self, budget_bytes: Callable[[], int]) -> None:
        """Bind admission to the current dynamically resolved cache budget."""

        self._budget_bytes = budget_bytes
        self._guard: Callable[[int], bool] | None = None
        self._rejected_keys: set[object] = set()

    def set_guard(self, guard: Callable[[int], bool] | None) -> None:
        """Install the shared cache coordinator's admission predicate."""

        self._guard = guard

    def can_retain(self, size_bytes: int) -> bool:
        """Return whether optional cache state can retain one derived raster."""

        return size_bytes <= self._budget_bytes() and (
            self._guard is None or self._guard(size_bytes)
        )

    def admit(self, size_bytes: int, key: object) -> bool:
        """Return admission and log the first rejection for an exact product."""

        if self.can_retain(size_bytes):
            return True
        if key not in self._rejected_keys:
            logger.warning(
                "requested item exceeds budget; not cached | "
                "consumer=mask_overlays | size=%d | budget=%d",
                size_bytes,
                self._budget_bytes(),
            )
            self._rejected_keys.add(key)
        return False

    def clear_rejections(self) -> None:
        """Forget diagnostics identities after the owning cache is cleared."""

        self._rejected_keys.clear()


def estimate_argb_presentation_bytes(image: QImage) -> int:
    """Estimate the colorized presentation product derived from an image."""

    return max(0, image.width()) * max(0, image.height()) * 4


__all__ = ["MaskRenderAdmission", "estimate_argb_presentation_bytes"]
