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
"""InteractionApi behavior for the CuteCanvas facade."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtGui import QPainter

from cutecanvas.core import (
    CursorProvider,
    ToolFactory,
    ToolSignalBinder,
)
from cutecanvas.cursor import EditorCursorTheme
from cutecanvas.edit_sessions import EditorToolDescriptor
from cutecanvas.overlay_contracts import (
    CanvasOverlayDrawFn,
    CanvasOverlayState,
)
from cutecanvas.tools import Tools
from qpane.sdk.overlays import OverlayDrawFn, SceneOverlayDrawFn
from qpane.sdk.types import OverlayState

from .edit_session_api import EditSessionApiMixin


class InteractionApiMixin(EditSessionApiMixin):
    """Group interactionapi facade behavior."""

    def availableControlModes(self) -> tuple[str, ...]:
        """Return registered tool modes in activation order."""
        return self._tools_manager.available_modes()

    def toolDescriptor(self, mode: str) -> EditorToolDescriptor:
        """Return declarative behavior for one registered editor tool."""
        return self._tools_manager.descriptor(mode)

    def toolDescriptors(self) -> tuple[EditorToolDescriptor, ...]:
        """Return declarative behavior for every registered editor tool."""
        return self._tools_manager.descriptors()

    def getControlMode(self) -> str:
        """Return the active tool mode."""
        return self._tools_manager.get_control_mode()

    def registerOverlay(self, name: str, draw_fn: OverlayDrawFn) -> None:
        """Register a viewport-space overlay."""
        self.interaction.registerOverlay(name, draw_fn)

    def registerCanvasOverlay(
        self,
        name: str,
        draw_fn: CanvasOverlayDrawFn,
    ) -> None:
        """Register a renderer-neutral viewport overlay for a CuteCanvas host."""

        def draw_native(painter: QPainter, state: OverlayState) -> None:
            """Adapt private QPane overlay data at the single facade boundary."""

            draw_fn(painter, CanvasOverlayState.from_native(state))

        self.interaction.registerOverlay(name, draw_native)

    def unregisterOverlay(self, name: str) -> None:
        """Remove a viewport-space overlay when present."""
        self.interaction.unregisterOverlay(name)

    def unregisterCanvasOverlay(self, name: str) -> None:
        """Remove a renderer-neutral viewport overlay when present."""

        self.interaction.unregisterOverlay(name)

    def contentOverlays(self) -> Mapping[str, OverlayDrawFn]:
        """Return registered viewport-space overlays."""
        return self.interaction.content_overlays_snapshot()

    def registerSceneOverlay(
        self,
        name: str,
        draw_fn: SceneOverlayDrawFn,
    ) -> None:
        """Register a scene overlay painted relative to layered scene composition layers.

        Raises:
            ValueError: If `name` is already present.
        """
        self.interaction.registerSceneOverlay(name, draw_fn)

    def unregisterSceneOverlay(self, name: str) -> None:
        """Remove a previously registered scene overlay."""
        self.interaction.unregisterSceneOverlay(name)

    def sceneOverlays(self) -> Mapping[str, SceneOverlayDrawFn]:
        """Return a read-only snapshot of registered scene overlays."""
        return self.interaction.scene_overlays_snapshot()

    def overlaysSuspended(self) -> bool:
        """Return True when interaction-managed overlays are currently suppressed."""
        return self.interaction.overlays_suspended

    def overlaysResumePending(self) -> bool:
        """Indicate overlays should resume once pending activation work finishes."""
        return self.interaction.overlays_resume_pending

    def resumeOverlays(self) -> None:
        """Allow overlay drawing to resume on the next paint."""
        self.interaction.resume_overlays()

    def resumeOverlaysAndUpdate(self) -> None:
        """Resume overlays and trigger a repaint."""
        self.interaction.resume_overlays_and_update()

    def maybeResumeOverlays(self) -> None:
        """Resume overlays when activation has completed for the active image."""
        self.interaction.maybe_resume_overlays()

    def registerCursorProvider(self, mode: str, provider: CursorProvider) -> None:
        """Attach a cursor provider via the supported facade helper.

        If the mode is active when this is called, the cursor updates immediately.
        """
        self.interaction.registerCursorProvider(mode, provider)

    def unregisterCursorProvider(self, mode: str) -> None:
        """Detach a previously registered cursor provider."""
        self.interaction.unregisterCursorProvider(mode)

    def setEditorCursorTheme(self, theme: EditorCursorTheme | None) -> None:
        """Set optional host artwork for built-in semantic cursor feedback."""

        self.interaction.setEditorCursorTheme(theme)

    def registerTool(
        self,
        mode: str,
        factory: ToolFactory,
        *,
        on_connect: ToolSignalBinder | None = None,
        on_disconnect: ToolSignalBinder | None = None,
    ) -> None:
        """Register a custom control mode through the supported facade API.

        Args:
            mode: Unique identifier for the tool mode.
            factory: Callable that creates a tool instance when the mode activates.
            on_connect: Optional binder for wiring tool-specific signals.
            on_disconnect: Optional binder invoked during teardown to unwire signals.
        """
        self.hooks.registerTool(
            mode,
            factory,
            on_connect=on_connect,
            on_disconnect=on_disconnect,
        )

    def unregisterTool(self, mode: str) -> None:
        """Remove a previously registered tool mode via the supported facade."""
        self.hooks.unregisterTool(mode)

    def setControlMode(
        self,
        mode: str,
    ) -> bool:
        """Select a persistent control mode and report whether it was accepted."""
        painting = self.paintingCoordinator()
        if mode == Tools.CONTROL_MODE_CLONE_STAMP:
            painting.set_stroke_operation(self.cloneStampOperation())
        else:
            painting.use_direct_stroke_operation()
        return self.interaction.set_control_mode(mode)
