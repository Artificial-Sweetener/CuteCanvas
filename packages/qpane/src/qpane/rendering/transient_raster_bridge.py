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

"""Coordinate transient raster providers with rendered-plan admission."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from ..scene.raster import RasterBounds
from ..scene.render_plan import SceneRenderItem, TransientRasterContribution

TransientRasterTarget = tuple[uuid.UUID, uuid.UUID, RasterBounds]
TransientRasterProvider = Callable[
    [tuple[SceneRenderItem, ...]], TransientRasterContribution | None
]
TransientRasterTargetProvider = Callable[[], TransientRasterTarget | None]
TransientRasterAdmissionObserver = Callable[[TransientRasterContribution], None]


class TransientRasterBridge:
    """Own provider calls and acknowledge contributions admitted for painting."""

    def __init__(self) -> None:
        """Initialize with inert provider boundaries."""
        self._provider: TransientRasterProvider = lambda _items: None
        self._target_provider: TransientRasterTargetProvider = lambda: None
        self._admission_observer: TransientRasterAdmissionObserver = (
            lambda _contribution: None
        )

    def configure(
        self,
        provider: TransientRasterProvider,
        target_provider: TransientRasterTargetProvider,
        admission_observer: TransientRasterAdmissionObserver,
    ) -> None:
        """Install one complete transient raster integration boundary."""
        self._provider = provider
        self._target_provider = target_provider
        self._admission_observer = admission_observer

    def shutdown(self) -> None:
        """Release every host callback during rendering teardown."""
        self._provider = lambda _items: None
        self._target_provider = lambda: None
        self._admission_observer = lambda _contribution: None

    def compile(
        self,
        render_items: tuple[SceneRenderItem, ...],
    ) -> TransientRasterContribution | None:
        """Compile the current contribution without consuming provider state."""
        return self._provider(render_items)

    def target(self) -> TransientRasterTarget | None:
        """Return the active transient raster's source-local support."""
        return self._target_provider()

    def admit(self, contribution: TransientRasterContribution | None) -> None:
        """Acknowledge one contribution after its plan reaches painting."""
        if contribution is not None:
            self._admission_observer(contribution)


__all__ = [
    "TransientRasterAdmissionObserver",
    "TransientRasterBridge",
    "TransientRasterProvider",
    "TransientRasterTarget",
    "TransientRasterTargetProvider",
]
