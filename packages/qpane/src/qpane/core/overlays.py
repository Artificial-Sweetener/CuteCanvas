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
"""Host-drawn overlay contracts shared by viewer and rendering presenter."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol

from PySide6.QtGui import QPainter

if TYPE_CHECKING:
    from ..types import OverlayState, SceneSnapshotOverlayState


class OverlayDrawFn(Protocol):
    """Draw host chrome after all scene content."""

    def __call__(self, painter: QPainter, state: OverlayState) -> None:
        """Render one content-relative overlay."""
        ...


class SceneOverlayDrawFn(Protocol):
    """Draw host chrome with ordered scene-layer context."""

    def __call__(self, painter: QPainter, state: SceneSnapshotOverlayState) -> None:
        """Render one scene-relative overlay."""
        ...


class OverlayRegistry:
    """Own uniquely named content and scene overlay contributions."""

    def __init__(self, changed: Callable[[], None] | None = None) -> None:
        """Create empty registries and retain an optional repaint callback."""
        self._changed = changed
        self._content: dict[str, OverlayDrawFn] = {}
        self._scene: dict[str, SceneOverlayDrawFn] = {}
        self._content_view = MappingProxyType(self._content)
        self._scene_view = MappingProxyType(self._scene)

    @property
    def content(self) -> Mapping[str, OverlayDrawFn]:
        """Return a live read-only view of content overlays."""
        return self._content_view

    @property
    def scene(self) -> Mapping[str, SceneOverlayDrawFn]:
        """Return a live read-only view of scene overlays."""
        return self._scene_view

    def content_snapshot(self) -> Mapping[str, OverlayDrawFn]:
        """Return a detached read-only snapshot of content overlays."""
        return MappingProxyType(dict(self._content))

    def scene_snapshot(self) -> Mapping[str, SceneOverlayDrawFn]:
        """Return a detached read-only snapshot of scene overlays."""
        return MappingProxyType(dict(self._scene))

    def register_content(self, name: str, draw_fn: OverlayDrawFn) -> None:
        """Register one uniquely named content overlay."""
        if name in self._content:
            raise ValueError(f"Overlay {name!r} is already registered")
        self._content[name] = draw_fn
        self._notify_changed()

    def unregister_content(self, name: str) -> None:
        """Remove one content overlay when present."""
        if self._content.pop(name, None) is not None:
            self._notify_changed()

    def register_scene(self, name: str, draw_fn: SceneOverlayDrawFn) -> None:
        """Register one uniquely named scene overlay."""
        if name in self._scene:
            raise ValueError(f"Scene overlay {name!r} is already registered")
        self._scene[name] = draw_fn
        self._notify_changed()

    def unregister_scene(self, name: str) -> None:
        """Remove one scene overlay when present."""
        if self._scene.pop(name, None) is not None:
            self._notify_changed()

    def _notify_changed(self) -> None:
        """Request a repaint after effective registry mutation."""
        if self._changed is not None:
            self._changed()
