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

"""Own the bounded lifetime of role-specific workspace target renderers."""

from __future__ import annotations

import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterable

from PySide6.QtWidgets import QWidget

from ..canvas import CuteCanvas
from ..document import CanvasPresentationKind
from .target_mount import CanvasTargetMount

CanvasViewKey = tuple[CanvasPresentationKind, uuid.UUID]


class CanvasTargetPool:
    """Retain exactly the target canvases required by one presentation."""

    def __init__(
        self,
        parent: QWidget,
        *,
        create_canvas: Callable[[uuid.UUID, CanvasPresentationKind], CuteCanvas],
        inactive_capacity: int,
    ) -> None:
        """Bind the stable workspace parent and target-canvas factory."""

        if inactive_capacity < 0:
            raise ValueError("inactive_capacity must not be negative")
        self._parent = parent
        self._create_canvas = create_canvas
        self._inactive_capacity = inactive_capacity
        self._canvases: dict[CanvasViewKey, CuteCanvas] = {}
        self._mounts: dict[CanvasViewKey, CanvasTargetMount] = {}
        self._recency: OrderedDict[CanvasViewKey, None] = OrderedDict()

    def values(self) -> tuple[CuteCanvas, ...]:
        """Return the currently retained target canvases."""

        return tuple(self._canvases.values())

    def canvas_for(
        self,
        composition_id: uuid.UUID,
        *,
        preferred_role: CanvasPresentationKind,
    ) -> CuteCanvas | None:
        """Return a preferred role target or another currently retained view."""

        preferred = self._canvases.get((preferred_role, composition_id))
        if preferred is not None:
            return preferred
        return next(
            (
                canvas
                for (role, target_id), canvas in self._canvases.items()
                if target_id == composition_id
            ),
            None,
        )

    def ensure(
        self,
        target_id: uuid.UUID,
        *,
        view_role: CanvasPresentationKind,
    ) -> CuteCanvas:
        """Return an existing target canvas or create its mount exactly once."""

        key = (view_role, target_id)
        canvas = self._canvases.get(key)
        if canvas is not None:
            self._touch(key)
            return canvas
        canvas = self._create_canvas(target_id, view_role)
        self._canvases[key] = canvas
        self._mounts[key] = CanvasTargetMount(canvas, self._parent)
        self._touch(key)
        return canvas

    def mount(
        self,
        target_id: uuid.UUID,
        parent: QWidget,
        *,
        view_role: CanvasPresentationKind,
    ) -> CanvasTargetMount:
        """Move one lightweight target mount into the current presentation."""

        canvas = self.ensure(target_id, view_role=view_role)
        mount = self._mounts[(view_role, target_id)]
        if canvas.parent() is not mount:
            canvas.setParent(mount)
            canvas.setGeometry(mount.rect())
            canvas.show()
        mount.setParent(parent)
        mount.show()
        return mount

    def direct_canvas(
        self,
        target_id: uuid.UUID,
        parent: QWidget,
        *,
        view_role: CanvasPresentationKind,
    ) -> CuteCanvas:
        """Move one canvas directly into a host-provided custom surface."""

        canvas = self.ensure(target_id, view_role=view_role)
        canvas.setParent(parent)
        canvas.show()
        return canvas

    def activate(self, keys: Iterable[CanvasViewKey]) -> None:
        """Retain active targets plus a bounded least-recently-used inactive set."""

        active = set(keys)
        for key in active:
            if key in self._canvases:
                self._touch(key)
        inactive = tuple(key for key in self._recency if key not in active)
        excess = max(0, len(inactive) - self._inactive_capacity)
        for key in inactive[:excess]:
            self._retire(key)
        for key in inactive[excess:]:
            self._park(key)

    def retire_unavailable(self, available: set[uuid.UUID]) -> None:
        """Close target renderers whose document compositions disappeared."""

        for key in tuple(self._canvases):
            if key[1] not in available:
                self._retire(key)

    def contains_mount(self, widget: QWidget) -> bool:
        """Return whether the widget is one of the pool's live mounts."""

        return widget in self._mounts.values()

    def close(self) -> None:
        """Close all target renderers and mounts exactly once."""

        for key in tuple(self._canvases):
            self._retire(key)

    def _touch(self, key: CanvasViewKey) -> None:
        """Mark one target as the most recently required renderer."""

        self._recency.pop(key, None)
        self._recency[key] = None

    def _park(self, key: CanvasViewKey) -> None:
        """Move one retained inactive target under the stable pool parent."""

        canvas = self._canvases[key]
        mount = self._mounts[key]
        if canvas.parent() is not mount:
            canvas.setParent(mount)
            canvas.setGeometry(mount.rect())
            canvas.show()
        mount.setParent(self._parent)
        mount.hide()

    def _retire(self, key: CanvasViewKey) -> None:
        """Release one canvas scope and its lightweight mount."""

        canvas = self._canvases.pop(key)
        mount = self._mounts.pop(key)
        self._recency.pop(key, None)
        try:
            canvas.close()
            canvas.setParent(None)
            canvas.deleteLater()
        except RuntimeError:
            pass
        try:
            mount.setParent(None)
            mount.close()
            mount.deleteLater()
        except RuntimeError:
            pass


__all__ = ["CanvasTargetPool", "CanvasViewKey"]
