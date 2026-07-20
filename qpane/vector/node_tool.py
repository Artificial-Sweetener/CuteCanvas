#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Focused direct-selection tool for semantic vector control points."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QCursor, QKeyEvent, QMouseEvent, QPainter

from ..tools.base import BaseTool
from ..tools.input.model import PointerPhase, PointerSample
from ..tools.input.profile import ToolInputProfile
from ..tools.ports import VectorNodeInteractionPort
from ..ui.vector_nodes import VectorNodeOverlayRenderer

VECTOR_NODE_MODE = "vector-node"


class VectorNodeTool(BaseTool):
    """Select and drag semantic nodes through one focused editor port."""

    input_profile = ToolInputProfile(touch=True, tablet=True)

    def __init__(self) -> None:
        """Initialize an inactive direct-selection tool."""
        super().__init__()
        self._port = VectorNodeInteractionPort()
        self._renderer = VectorNodeOverlayRenderer()
        self._pressed = False

    def activate(self, dependencies: VectorNodeInteractionPort) -> None:
        """Capture the focused node-edit boundary without resetting its session."""
        self._port = dependencies

    def deactivate(self) -> None:
        """Suspend input while retaining unresolved domain preview state."""
        self._pressed = False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Select an object or begin one node drag on primary press."""
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        self._pressed = self._port.begin(QPointF(event.position()))
        if not self._pressed:
            event.ignore()
            return
        self.signals.repaint_overlay_requested.emit()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Update immediate preview geometry during a captured node drag."""
        if not self._pressed or not (event.buttons() & Qt.MouseButton.LeftButton):
            event.ignore()
            return
        self._port.update(QPointF(event.position()))
        self.signals.repaint_overlay_requested.emit()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Commit one history edit when an active node drag ends."""
        if event.button() != Qt.MouseButton.LeftButton or not self._pressed:
            event.ignore()
            return
        self._port.finish(QPointF(event.position()))
        self._pressed = False
        self.signals.repaint_overlay_requested.emit()
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Cancel only unresolved node preview geometry with Escape."""
        if event.key() != Qt.Key.Key_Escape or not self._port.cancel():
            event.ignore()
            return
        self._pressed = False
        self.signals.repaint_overlay_requested.emit()
        event.accept()

    def handle_pointer_sample(self, sample: PointerSample) -> bool:
        """Route touch/tablet contact through the same node-edit lifecycle."""
        if sample.phase is PointerPhase.BEGIN:
            self._pressed = self._port.begin(sample.position)
            return self._pressed
        if sample.phase is PointerPhase.UPDATE and self._pressed:
            return self._port.update(sample.position)
        if sample.phase is PointerPhase.END and self._pressed:
            self._pressed = False
            return self._port.finish(sample.position)
        if sample.phase is PointerPhase.CANCEL and self._pressed:
            self._pressed = False
            return self._port.cancel()
        return False

    def draw_overlay(self, painter: QPainter) -> None:
        """Delegate detached node feedback to the UI renderer."""
        self._renderer.draw(painter, self._port.overlay_state())

    def getCursor(self) -> QCursor | None:
        """Return the direct-selection arrow cursor."""
        return QCursor(Qt.CursorShape.ArrowCursor)
