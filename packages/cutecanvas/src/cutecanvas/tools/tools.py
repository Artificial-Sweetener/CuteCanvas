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
"""CuteCanvas registrations layered on QPane's authoritative tool manager."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QPoint, Signal

from cutecanvas.edit_sessions import (
    EditorToolDescriptor,
    EditSessionKind,
    ToolEditSessionDeclaration,
)
from qpane import (
    CursorTool,
    PanZoomTool,
    ToolManager,
    ViewerTool,
)
from qpane import (
    ToolManagerSignals as ViewerToolManagerSignals,
)

from .move import MoveTool
from .paint_bucket import PaintBucketTool
from .polygon_coverage import PolygonCoverageTool
from .ports import ToolActivationPorts
from .selection_shapes import (
    EllipseSelectionTool,
    LassoSelectionTool,
    RectangleSelectionTool,
)
from .shared_edge_resize import SharedEdgeResizeTool
from .transform import TransformTool


class ToolManagerSignals(ViewerToolManagerSignals):
    """Add editor-domain requests to QPane's source-neutral tool signal bus."""

    stroke_applied = Signal(object)
    stroke_completed = Signal()
    stroke_cancelled = Signal()
    brush_size_changed = Signal(int)
    undo_state_push_requested = Signal()
    smart_segmentation_requested = Signal(object)
    mask_component_adjustment_requested = Signal(QPoint, bool)


ToolSignalBinder = Callable[[ToolManagerSignals, ViewerTool], None]


class Tools(ToolManager):
    """Register CuteCanvas editor tools in QPane's shared lifecycle host."""

    CONTROL_MODE_PANZOOM = "panzoom"
    CONTROL_MODE_CURSOR = "cursor"
    CONTROL_MODE_MOVE = "move"
    CONTROL_MODE_TRANSFORM = "transform"
    CONTROL_MODE_SHARED_EDGE_RESIZE = "shared-edge-resize"
    CONTROL_MODE_DRAW_BRUSH = "draw-brush"
    CONTROL_MODE_ERASER = "eraser"
    CONTROL_MODE_CLONE_STAMP = "clone-stamp"
    CONTROL_MODE_PAINT_BUCKET = "paint-bucket"
    CONTROL_MODE_SMART_SELECT = "smart-select"
    CONTROL_MODE_SMART_MASK = "smart-mask"
    CONTROL_MODE_SELECT_RECTANGLE = "select-rectangle"
    CONTROL_MODE_SELECT_ELLIPSE = "select-ellipse"
    CONTROL_MODE_SELECT_LASSO = "select-lasso"
    CONTROL_MODE_SELECT_POLYGON = "select-polygon"
    CONTROL_MODE_MASK_RECTANGLE = "mask-rectangle"
    CONTROL_MODE_MASK_ELLIPSE = "mask-ellipse"
    CONTROL_MODE_MASK_LASSO = "mask-lasso"
    CONTROL_MODE_MASK_POLYGON = "mask-polygon"

    def __init__(self, parent: QObject | None = None) -> None:
        """Install viewer tools and the factory editor tool set."""
        signals = ToolManagerSignals()
        super().__init__(parent, signals=signals)
        self.signals: ToolManagerSignals = signals
        self._activation_ports = ToolActivationPorts()
        self._descriptors: dict[str, EditorToolDescriptor] = {}
        from ..painting.tools import (
            BrushTool,
            CloneStampTool,
            EraserTool,
            connect_brush_signals,
            disconnect_brush_signals,
        )

        self.registerTool(self.CONTROL_MODE_PANZOOM, PanZoomTool)
        self.registerTool(self.CONTROL_MODE_CURSOR, CursorTool)
        self.registerTool(self.CONTROL_MODE_MOVE, MoveTool)
        self.registerTool(
            self.CONTROL_MODE_TRANSFORM,
            TransformTool,
            edit_session=ToolEditSessionDeclaration(EditSessionKind.TRANSFORM),
        )
        self.registerTool(
            self.CONTROL_MODE_SHARED_EDGE_RESIZE,
            SharedEdgeResizeTool,
            edit_session=ToolEditSessionDeclaration(EditSessionKind.SHARED_EDGE_RESIZE),
        )
        self.registerTool(self.CONTROL_MODE_PAINT_BUCKET, PaintBucketTool)
        self.registerTool(self.CONTROL_MODE_SELECT_RECTANGLE, RectangleSelectionTool)
        self.registerTool(self.CONTROL_MODE_SELECT_ELLIPSE, EllipseSelectionTool)
        self.registerTool(self.CONTROL_MODE_SELECT_LASSO, LassoSelectionTool)
        self.registerTool(
            self.CONTROL_MODE_SELECT_POLYGON,
            PolygonCoverageTool,
            edit_session=ToolEditSessionDeclaration(EditSessionKind.POLYGON_SELECTION),
        )
        self.registerTool(self.CONTROL_MODE_MASK_RECTANGLE, RectangleSelectionTool)
        self.registerTool(self.CONTROL_MODE_MASK_ELLIPSE, EllipseSelectionTool)
        self.registerTool(self.CONTROL_MODE_MASK_LASSO, LassoSelectionTool)
        self.registerTool(
            self.CONTROL_MODE_MASK_POLYGON,
            PolygonCoverageTool,
            edit_session=ToolEditSessionDeclaration(EditSessionKind.POLYGON_MASK),
        )
        self.registerTool(
            self.CONTROL_MODE_DRAW_BRUSH,
            BrushTool,
            on_connect=connect_brush_signals,
            on_disconnect=disconnect_brush_signals,
        )
        self.registerTool(
            self.CONTROL_MODE_ERASER,
            EraserTool,
            on_connect=connect_brush_signals,
            on_disconnect=disconnect_brush_signals,
        )
        self.registerTool(
            self.CONTROL_MODE_CLONE_STAMP,
            CloneStampTool,
            on_connect=connect_brush_signals,
            on_disconnect=disconnect_brush_signals,
        )

    def registerTool(
        self,
        mode: str,
        factory: Callable[[], ViewerTool],
        *,
        edit_session: ToolEditSessionDeclaration | None = None,
        on_connect: ToolSignalBinder | None = None,
        on_disconnect: ToolSignalBinder | None = None,
    ) -> None:
        """Register an editor mode in the shared QPane lifecycle host."""
        self.register(
            mode,
            factory,
            lambda mode=mode: self._activation_ports.for_mode(mode),
            on_connect=on_connect,
            on_disconnect=on_disconnect,
        )
        self._descriptors[mode] = EditorToolDescriptor(mode, edit_session)

    def unregisterTool(self, mode: str) -> None:
        """Remove an inactive editor tool while protecting Pan/Zoom."""
        if mode == self.CONTROL_MODE_PANZOOM:
            raise ValueError("Pan/zoom tool cannot be unregistered")
        self.unregister(mode)
        self._descriptors.pop(mode, None)

    def descriptor(self, mode: str) -> EditorToolDescriptor:
        """Return detached declarative behavior for one registered tool."""
        try:
            return self._descriptors[mode]
        except KeyError as error:
            raise ValueError(f"Unknown control mode: {mode}") from error

    def descriptors(self) -> tuple[EditorToolDescriptor, ...]:
        """Return every registered tool descriptor in registration order."""
        return tuple(self._descriptors.values())

    def set_mode(
        self,
        mode: str,
        ports: ToolActivationPorts | None = None,
    ) -> None:
        """Activate an editor mode with the current focused domain ports."""
        if ports is not None:
            self._activation_ports = ports
        self.activate(mode, force=ports is not None)

    def get_active_tool(self) -> ViewerTool | None:
        """Return the currently active QPane-hosted tool."""
        return self.active_tool

    def get_control_mode(self) -> str:
        """Return the active mode, defaulting to Pan/Zoom before activation."""
        return self.active_mode or self.CONTROL_MODE_PANZOOM
