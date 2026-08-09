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

"""Point-by-point interaction for unfinished polygon coverage authorship."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import ClassVar

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPainter
from qpane import PointerPhase, PointerSample, ToolInputProfile

from cutecanvas.coverage import CoverageCombineMode
from cutecanvas.cursor import EditorCursorIntent

from .base import BaseTool
from .coverage_operation import resolve_coverage_gesture_operation
from .cursor_feedback import ToolCursorStyle
from .modifier_snapshot import alt_is_active, shift_is_active, snapping_is_suppressed
from .polygon_coverage_hit_testing import point_distance
from .polygon_coverage_overlay import (
    PolygonCoveragePresentation,
    draw_polygon_coverage_overlay,
)
from .polygon_coverage_publication import PolygonCoveragePublication
from .polygon_coverage_session import PolygonCoverageSession
from .ports import AuthoringSnapPort, PixelSelectionInteractionPort

_DRAG_THRESHOLD = 2.0


class PolygonCoverageTool(BaseTool):
    """Author one revisable retained polygon before publishing a single edit."""

    input_profile = ToolInputProfile(touch=True, tablet=True)
    cursor_style: ClassVar[ToolCursorStyle] = ToolCursorStyle.PRECISE
    supports_alt_erase_indicator: ClassVar[bool] = True

    def __init__(self) -> None:
        """Initialize an idle polygon interaction and inert dependencies."""
        super().__init__()
        self._reset_dependencies()
        self._session: PolygonCoverageSession | None = None
        self._selected_id = None
        self._drag_id = None
        self._press_panel: QPointF | None = None
        self._close_candidate = False
        self._pointer_panel: QPointF | None = None
        self._hover_vertex_id: uuid.UUID | None = None
        self._hover_edge_index: int | None = None
        self._combine_mode = CoverageCombineMode.REPLACE

    @property
    def authoring(self) -> bool:
        """Return whether an unfinished polygon currently owns input."""
        return self._session is not None

    def activate(self, dependencies: PixelSelectionInteractionPort) -> None:
        """Capture target projection, coverage, policy, and snapping collaborators."""
        self._panel_to_target = dependencies.panel_to_scene_point
        self._presentation = PolygonCoveragePresentation(
            dependencies.target_to_panel_point
        )
        self._can_author = dependencies.can_select
        self._has_coverage = dependencies.has_selection
        self._alt_constrains_empty = dependencies.alt_constrains_empty_shape
        self._is_shift_held = dependencies.is_shift_held
        self._is_alt_held = dependencies.is_alt_held
        self._default_combine_mode = dependencies.default_combine_mode
        self._snapping = dependencies.snapping
        self._publication = PolygonCoveragePublication(
            commit=dependencies.commit_coverage_item,
            constrain=dependencies.constrain_coverage_item,
            feather_radius=dependencies.get_shape_feather_radius,
        )

    def deactivate(self) -> None:
        """Discard unfinished geometry and release every collaborator."""
        self._cancel()
        self._reset_dependencies()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Place, select, or insert a vertex on a primary-button press."""
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        if self._press(QPointF(event.position()), event.modifiers()):
            event.accept()
        else:
            event.ignore()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Move a selected vertex or update idle authoring affordances."""
        point = QPointF(event.position())
        if self._drag_id is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._move_drag(point, event.modifiers())
            event.accept()
            return
        self._update_hover(point, event.modifiers())
        event.ignore()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Finish a vertex manipulation or close through a first-vertex click."""
        if event.button() != Qt.MouseButton.LeftButton or self._drag_id is None:
            event.ignore()
            return
        self._release(QPointF(event.position()), event.modifiers())
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Finish valid unfinished geometry through the conventional double click."""
        if event.button() == Qt.MouseButton.LeftButton and self._finish():
            event.accept()
        else:
            event.ignore()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Finish, cancel, or remove vertices from the unfinished polygon."""
        if event.key() == Qt.Key.Key_Escape and self._session is not None:
            self._cancel()
            event.accept()
            return
        if event.key() in {Qt.Key.Key_Enter, Qt.Key.Key_Return} and self._finish():
            event.accept()
            return
        if event.key() == Qt.Key.Key_Backspace and self._remove_endpoint():
            event.accept()
            return
        if event.key() == Qt.Key.Key_Delete and self._remove_selected():
            event.accept()
            return
        event.ignore()

    def handle_pointer_sample(self, sample: PointerSample) -> bool:
        """Route pen and touch through the same unfinished authoring lifecycle."""
        if sample.phase is PointerPhase.BEGIN:
            return self._press(sample.position, sample.modifiers)
        if sample.phase is PointerPhase.UPDATE and self._drag_id is not None:
            self._move_drag(sample.position, sample.modifiers)
            return True
        if sample.phase is PointerPhase.END and self._drag_id is not None:
            self._release(sample.position, sample.modifiers)
            return True
        if sample.phase is PointerPhase.CANCEL and self._session is not None:
            self._cancel()
            return True
        return False

    def cursor_intent(self) -> EditorCursorIntent:
        """Describe whether polygon authorship is currently permitted."""
        return (
            EditorCursorIntent.PRECISE
            if self._can_author()
            else EditorCursorIntent.FORBIDDEN
        )

    def draw_overlay(self, painter: QPainter) -> None:
        """Present unfinished vertices and edges without rasterizing coverage."""
        state = self._presentation.state(
            self._session,
            pointer=self._pointer_panel,
            selected_id=self._selected_id,
            hovered_vertex_id=self._hover_vertex_id,
            hovered_edge_index=self._hover_edge_index,
        )
        if state is not None:
            draw_polygon_coverage_overlay(painter, state)

    def _press(
        self,
        panel_point: QPointF,
        modifiers: Qt.KeyboardModifier,
    ) -> bool:
        """Resolve one press into closure, vertex movement, insertion, or append."""
        if not self._can_author():
            return False
        session = self._session
        vertex_id = self._presentation.vertex_at(session, panel_point)
        if session is not None and vertex_id is not None:
            self._begin_drag(vertex_id, panel_point)
            self._close_candidate = (
                vertex_id == session.vertex_ids[0] and session.can_finish
            )
            return True
        self._snapping.clear()
        snapped = self._snapping.begin(
            panel_point,
            snapping_is_suppressed(modifiers),
        )
        target = self._panel_to_target(snapped)
        if target is None:
            return False
        if session is None:
            session = PolygonCoverageSession()
            self._session = session
            self._combine_mode = self._resolve_combine_mode(modifiers)
        edge_index = self._presentation.edge_at(session, panel_point)
        try:
            vertex_id = (
                session.append(target)
                if edge_index is None
                else session.insert_after(session.vertex_ids[edge_index], target)
            )
        except ValueError:
            return False
        self._begin_drag(vertex_id, panel_point)
        self._pointer_panel = QPointF(snapped)
        self._publish_overlay()
        return True

    def _begin_drag(self, vertex_id: uuid.UUID, panel_point: QPointF) -> None:
        """Select one stable vertex for the active press lifecycle."""
        self._selected_id = vertex_id
        self._drag_id = vertex_id
        self._press_panel = QPointF(panel_point)

    def _move_drag(
        self,
        panel_point: QPointF,
        modifiers: Qt.KeyboardModifier,
    ) -> None:
        """Move the active stable vertex through snapping and target projection."""
        session = self._session
        vertex_id = self._drag_id
        if session is None or vertex_id is None:
            return
        if (
            self._press_panel is not None
            and point_distance(panel_point, self._press_panel) > _DRAG_THRESHOLD
        ):
            self._close_candidate = False
        snapped = self._snapping.update(
            panel_point,
            snapping_is_suppressed(modifiers),
            shift_is_active(self._is_shift_held(), modifiers),
        )
        target = self._panel_to_target(snapped)
        if target is None:
            return
        try:
            changed = session.move(vertex_id, target)
        except ValueError:
            return
        self._pointer_panel = QPointF(snapped)
        if changed:
            self._publish_overlay()

    def _release(
        self,
        panel_point: QPointF,
        modifiers: Qt.KeyboardModifier,
    ) -> None:
        """Resolve closure or retain the edited vertex in the open session."""
        if not self._close_candidate:
            self._move_drag(panel_point, modifiers)
        close = self._close_candidate
        self._drag_id = None
        self._press_panel = None
        self._close_candidate = False
        if close:
            self._finish()
        else:
            self._update_hover(panel_point, modifiers)

    def _finish(self) -> bool:
        """Commit valid coverage once and discard all transient topology."""
        session = self._session
        if session is None or not session.can_finish:
            return False
        if not self._publication.publish(session.points, self._combine_mode):
            return False
        self._clear()
        return True

    def _cancel(self) -> bool:
        """Discard the entire unfinished polygon without publishing coverage."""
        if self._session is None:
            return False
        self._clear()
        return True

    def _clear(self) -> None:
        """Return the tool to idle and release snapping hysteresis."""
        self._snapping.clear()
        self._session = None
        self._selected_id = None
        self._drag_id = None
        self._press_panel = None
        self._pointer_panel = None
        self._hover_vertex_id = None
        self._hover_edge_index = None
        self._close_candidate = False
        self._publish_overlay()

    def _remove_endpoint(self) -> bool:
        """Remove the open endpoint while retaining any earlier chain."""
        session = self._session
        endpoint = None if session is None else session.open_endpoint_id
        if session is None or endpoint is None:
            return False
        session.remove(endpoint)
        self._selected_id = session.open_endpoint_id
        if not session.vertex_ids:
            self._clear()
        else:
            self._publish_overlay()
        return True

    def _remove_selected(self) -> bool:
        """Remove the selected prior vertex without changing the open endpoint."""
        session = self._session
        if session is None or self._selected_id is None:
            return False
        if not session.remove(self._selected_id):
            return False
        self._selected_id = session.open_endpoint_id
        if not session.vertex_ids:
            self._clear()
        else:
            self._publish_overlay()
        return True

    def _update_hover(
        self,
        panel_point: QPointF,
        modifiers: Qt.KeyboardModifier,
    ) -> None:
        """Update closure, insertion, and provisional endpoint feedback."""
        self._pointer_panel = QPointF(panel_point)
        self._hover_vertex_id = self._presentation.vertex_at(
            self._session,
            panel_point,
        )
        self._hover_edge_index = (
            None
            if self._hover_vertex_id is not None
            else self._presentation.edge_at(self._session, panel_point)
        )
        if self._session is not None and self._hover_vertex_id is None:
            self._pointer_panel = self._snapping.update(
                panel_point,
                snapping_is_suppressed(modifiers),
                shift_is_active(self._is_shift_held(), modifiers),
            )
        self._publish_overlay()

    def _resolve_combine_mode(
        self,
        modifiers: Qt.KeyboardModifier,
    ) -> CoverageCombineMode:
        """Capture familiar selection algebra when the first vertex is placed."""
        alt = alt_is_active(self._is_alt_held(), modifiers)
        return resolve_coverage_gesture_operation(
            default=self._default_combine_mode,
            alt_held=alt,
            shift_held=shift_is_active(self._is_shift_held(), modifiers),
            has_coverage=self._has_coverage(),
            alt_constrains_empty=self._alt_constrains_empty,
        )

    def _publish_overlay(self) -> None:
        """Request repaint and cursor refresh after semantic hover or topology changes."""
        self.signals.repaint_overlay_requested.emit()
        self.signals.cursor_update_requested.emit()

    def _reset_dependencies(self) -> None:
        """Install inert collaborators for safe teardown before activation."""
        self._panel_to_target: Callable[[QPointF], QPointF | None] = lambda _point: None
        self._presentation = PolygonCoveragePresentation(QPointF)
        self._can_author: Callable[[], bool] = lambda: False
        self._has_coverage: Callable[[], bool] = lambda: False
        self._alt_constrains_empty = False
        self._is_shift_held: Callable[[], bool] = lambda: False
        self._is_alt_held: Callable[[], bool] = lambda: False
        self._default_combine_mode = CoverageCombineMode.REPLACE
        self._snapping = AuthoringSnapPort()
        self._publication = PolygonCoveragePublication(
            commit=lambda _item: False,
            constrain=lambda item: item,
            feather_radius=lambda: 0.0,
        )


__all__ = ["PolygonCoverageTool"]
