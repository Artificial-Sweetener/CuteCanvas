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
"""Editor overlay registration and temporary suspension ownership."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from qpane.sdk.overlays import OverlayDrawFn, OverlayRegistry, SceneOverlayDrawFn


class EditorOverlayController:
    """Own registered editor overlays and navigation suspension state."""

    def __init__(self, repaint: Callable[[], None]) -> None:
        """Capture the widget repaint boundary and initialize visible overlays."""
        self._repaint = repaint
        self._registry = OverlayRegistry(repaint)
        self.suspended = False
        self.resume_pending = False

    @property
    def content(self) -> Mapping[str, OverlayDrawFn]:
        """Return the immutable content-overlay snapshot."""
        return self._registry.content

    @property
    def scene(self) -> Mapping[str, SceneOverlayDrawFn]:
        """Return the immutable scene-overlay snapshot."""
        return self._registry.scene

    def content_snapshot(self) -> Mapping[str, OverlayDrawFn]:
        """Return a detached read-only content-overlay snapshot."""
        return self._registry.content_snapshot()

    def scene_snapshot(self) -> Mapping[str, SceneOverlayDrawFn]:
        """Return a detached read-only scene-overlay snapshot."""
        return self._registry.scene_snapshot()

    def register_content(self, name: str, draw_fn: OverlayDrawFn) -> None:
        """Register one source-coordinate overlay."""
        self._registry.register_content(name, draw_fn)

    def unregister_content(self, name: str) -> None:
        """Remove one source-coordinate overlay when present."""
        self._registry.unregister_content(name)

    def register_scene(self, name: str, draw_fn: SceneOverlayDrawFn) -> None:
        """Register one scene-aware overlay."""
        self._registry.register_scene(name, draw_fn)

    def unregister_scene(self, name: str) -> None:
        """Remove one scene-aware overlay when present."""
        self._registry.unregister_scene(name)

    def suspend(self) -> None:
        """Hide overlays until the coordinating workflow permits resumption."""
        self.suspended = True
        self.resume_pending = True

    def resume(self, *, repaint: bool = False) -> None:
        """Clear suspension state and optionally schedule a new frame."""
        self.suspended = False
        self.resume_pending = False
        if repaint:
            self._repaint()
