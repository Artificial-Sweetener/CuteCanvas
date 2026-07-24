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
"""Clone Stamp interaction layered on the shared brush input pipeline."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QCursor, QMouseEvent, QPainter, QWheelEvent
from qpane import PointerPhase, PointerSample

from cutecanvas.tools.ports import CloneStampInteractionPort

from .brush import BrushTool
from .brush_preview import AffineBrushPreview, AffineBrushPreviewRenderer


class CloneStampTool(BrushTool):
    """Paint cloned pixels while adding only source-setting interaction."""

    def __init__(self) -> None:
        """Initialize shared stroke input and inert source dependencies."""
        super().__init__()
        self._clone_port = CloneStampInteractionPort()
        self._source_preview_renderer = AffineBrushPreviewRenderer()

    def activate(self, dependencies: CloneStampInteractionPort) -> None:
        """Bind shared painting input plus Clone Stamp source operations."""
        self._clone_port = dependencies
        super().activate(
            replace(
                dependencies.painting,
                is_alt_held=lambda: False,
            )
        )

    def deactivate(self) -> None:
        """Cancel provisional work and release source interaction callbacks."""
        super().deactivate()
        self._clone_port = CloneStampInteractionPort()

    def getCursor(self) -> QCursor | None:
        """Show source-pick and unavailable states before normal brush feedback."""
        if self._clone_port.painting.is_alt_held():
            return QCursor(Qt.CursorShape.CrossCursor)
        if not self._can_paint() or not self._clone_port.source_set():
            return QCursor(Qt.CursorShape.ForbiddenCursor)
        return super().getCursor()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Set the source with Alt-click or begin a shared brush stroke."""
        previous = self._source_feedback_preview()
        if event.button() == Qt.MouseButton.LeftButton and (
            self._clone_port.painting.is_alt_held()
            or bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
        ):
            if self._clone_port.set_source_from_panel(QPointF(event.position())):
                self._refresh_source_feedback(previous)
                self.signals.cursor_update_requested.emit()
                event.accept()
            return
        if not self._clone_port.source_set():
            return
        super().mousePressEvent(event)
        self._refresh_source_feedback(previous)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Move the sampled-area footprint with an active clone stroke."""
        previous = self._source_feedback_preview()
        super().mouseMoveEvent(event)
        self._refresh_source_feedback(previous)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Finish painting and return sampled-area feedback to its anchor."""
        previous = self._source_feedback_preview()
        super().mouseReleaseEvent(event)
        self._refresh_source_feedback(previous)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Resize both destination and sampled-area brush feedback."""
        previous = self._source_feedback_preview()
        super().wheelEvent(event)
        self._refresh_source_feedback(previous)

    def handle_pointer_sample(self, sample: PointerSample) -> bool:
        """Set a direct-input source on modified contact or paint normally."""
        previous = self._source_feedback_preview()
        if sample.phase is PointerPhase.BEGIN and (
            self._clone_port.painting.is_alt_held()
            or bool(sample.modifiers & Qt.KeyboardModifier.AltModifier)
        ):
            changed = self._clone_port.set_source_from_panel(sample.position)
            if changed:
                self._refresh_source_feedback(previous)
                self.signals.cursor_update_requested.emit()
            return changed
        if sample.phase is PointerPhase.BEGIN and not self._clone_port.source_set():
            return False
        handled = super().handle_pointer_sample(sample)
        self._refresh_source_feedback(previous)
        return handled

    def suspend_for_temporary_navigation(self) -> bool:
        """Commit painting and restore anchor feedback before navigation."""
        previous = self._source_feedback_preview()
        suspended = super().suspend_for_temporary_navigation()
        self._refresh_source_feedback(previous)
        return suspended

    def draw_overlay(self, painter: QPainter) -> None:
        """Draw destination feedback plus the sampled brush footprint."""
        super().draw_overlay(painter)
        preview = self._source_feedback_preview()
        if preview is None:
            return
        color = self._get_preview_color()
        self._source_preview_renderer.draw(
            painter,
            preview,
            color=color if color is not None else QColor(Qt.GlobalColor.white),
        )

    def _cancel_active_stroke(self) -> bool:
        """Cancel painting and restore sampled-area feedback to its anchor."""
        previous = self._source_feedback_preview()
        cancelled = super()._cancel_active_stroke()
        self._refresh_source_feedback(previous)
        return cancelled

    def _source_feedback_preview(self) -> AffineBrushPreview | None:
        """Describe the effective sampled area in current panel coordinates."""
        pointer_preview = self.pointer_preview
        diameter = (
            pointer_preview.diameter
            if self.is_drawing and pointer_preview is not None
            else float(self._get_brush_size())
        )
        return self._clone_port.source_footprint(diameter)

    def _refresh_source_feedback(self, previous: AffineBrushPreview | None) -> None:
        """Invalidate only the old and new sampled-area footprints."""
        current = self._source_feedback_preview()
        if current == previous:
            return
        dirty = None
        for preview in (previous, current):
            if preview is None:
                continue
            bounds = preview.logical_bounds()
            dirty = bounds if dirty is None else dirty.united(bounds)
        if dirty is not None:
            self._request_overlay_update(dirty)
