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
"""Own semantic viewport alignment across host geometry changes."""

from __future__ import annotations

from math import isclose

from PySide6.QtCore import QSize

from .viewport import Viewport, ViewportZoomMode


class ViewportResizeAlignment:
    """Distinguish responsive FIT geometry from invariant manual navigation."""

    def __init__(self, viewport: Viewport, initial_dpr: float) -> None:
        """Bind one viewport and initialize an unobserved logical size."""
        self._viewport = viewport
        self._last_size = QSize()
        self._last_dpr = float(initial_dpr)

    def align(self, size: QSize, dpr: float, *, force: bool = False) -> bool:
        """Align FIT transforms and report whether backing geometry must refresh.

        Manual zoom and pan already describe an image-space view independently
        of widget geometry. Reapplying either value would clamp that authored
        view against the new widget bounds and move its image-space center.
        """
        current_size = QSize(size)
        current_dpr = float(dpr)
        dpr_changed = not isclose(
            current_dpr,
            self._last_dpr,
            rel_tol=1e-9,
            abs_tol=1e-9,
        )
        if not force and current_size == self._last_size and not dpr_changed:
            return False
        if self._viewport.get_zoom_mode() is ViewportZoomMode.FIT:
            self._viewport.setZoomFit()
        self._last_size = current_size
        self._last_dpr = current_dpr
        return True
