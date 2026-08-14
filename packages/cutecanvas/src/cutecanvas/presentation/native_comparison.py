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

"""Project a CuteCanvas comparison presentation through one native QPane scene."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from math import hypot

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF
from PySide6.QtGui import (
    QContextMenuEvent,
    QMouseEvent,
    QPainter,
    QResizeEvent,
    QShowEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QVBoxLayout, QWidget

from qpane import QPane
from qpane.sdk.types import (
    ComparisonOrientation,
    LinkedGroup,
    SceneSnapshotOverlayState,
)

from ..document import CanvasComparison, CanvasDocument, CanvasViewSession
from ..runtime.document_runtime import CanvasDocumentRuntime
from .comparison_catalog import ComparisonCatalogSynchronizer
from .comparison_overlays import (
    CanvasComparisonDivider,
    CanvasComparisonOverlayDrawFn,
    CanvasComparisonOverlayState,
    CanvasComparisonScale,
    CanvasComparisonZoomGesture,
)


class NativeCanvasComparison(QWidget):
    """Own one QPane reveal scene backed by two CuteCanvas document targets."""

    def __init__(
        self,
        *,
        document: CanvasDocument,
        document_runtime: CanvasDocumentRuntime,
        session: CanvasViewSession,
        comparison: CanvasComparison,
        changed: Callable[[float, ComparisonOrientation], None],
        context_requested: Callable[[uuid.UUID, QPoint], None],
        zoom_gesture: Callable[[CanvasComparisonZoomGesture], None],
        pointer_moved: Callable[[QPointF], None],
        overlays: Mapping[str, CanvasComparisonOverlayDrawFn],
        parent: QWidget | None = None,
    ) -> None:
        """Build a native comparison without overlapping child canvas widgets."""
        super().__init__(parent)
        self._document = document
        self._session = session
        self._comparison = comparison
        self._changed = changed
        self._context_requested = context_requested
        self._zoom_gesture = zoom_gesture
        self._pointer_moved = pointer_moved
        self._comparison_overlays: dict[str, CanvasComparisonOverlayDrawFn] = {}
        self._zoom_gesture_position: QPointF | None = None
        self._inspection_restored = False
        self._pane = QPane(
            execution_runtime=document_runtime.execution_runtime,
            inspection=session.inspection,
        )
        self._pane.setComparisonDividerInteractive(True)
        self._pane.comparisonChanged.connect(self._comparison_changed)
        self._pane.zoomChanged.connect(self._zoom_changed)
        self._pane.installEventFilter(self)
        self._catalog = ComparisonCatalogSynchronizer(
            document,
            self._pane,
            self._title,
        )
        self.destroyed.connect(self._catalog.close)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._pane)
        for name, draw_fn in overlays.items():
            self.registerOverlay(name, draw_fn)
        self._present_comparison(comparison)

    @property
    def pane(self) -> QPane:
        """Return the sole native renderer used by this comparison surface."""
        return self._pane

    @property
    def comparison(self) -> CanvasComparison:
        """Return the current document-target comparison state."""
        return self._comparison

    def setComparison(
        self,
        comparison: CanvasComparison,
        *,
        capture_current: bool,
    ) -> None:
        """Apply a new pair through the persistent native comparison scene.

        Args:
            comparison: Document-owned reveal state to present.
            capture_current: Persist the visible pair before changing it.  The
                workspace disables this only after it has captured the old
                pair before changing that pair's inspection group.
        """
        if comparison == self._comparison:
            return
        same_pair = (
            comparison.primary_id == self._comparison.primary_id
            and comparison.secondary_id == self._comparison.secondary_id
        )
        if same_pair:
            self._comparison = comparison
            self._pane.setComparisonSplit(
                comparison.split_position,
                comparison.orientation,
            )
            return
        if capture_current:
            self._pane.captureCatalogInspection()
        self._comparison = comparison
        self._present_comparison(comparison)

    def release(self) -> None:
        """Persist the comparison viewport before this native pane is replaced."""
        self._pane.captureCatalogInspection()

    def registerOverlay(
        self,
        name: str,
        draw_fn: CanvasComparisonOverlayDrawFn,
    ) -> None:
        """Register one host comparison overlay without exposing the native pane."""

        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("comparison overlay name must not be blank")
        if normalized_name in self._comparison_overlays:
            raise ValueError(f"comparison overlay already exists: {normalized_name}")
        self._comparison_overlays[normalized_name] = draw_fn
        self._pane.registerSceneOverlay(
            normalized_name,
            lambda painter, state: self._draw_overlay(normalized_name, painter, state),
        )

    def unregisterOverlay(self, name: str) -> None:
        """Remove one host comparison overlay when it is currently registered."""

        if self._comparison_overlays.pop(name, None) is not None:
            self._pane.unregisterSceneOverlay(name)

    def refreshOverlays(self) -> None:
        """Request a paint after a host overlay changes its transient state."""

        self._pane.update()

    def showEvent(self, event: QShowEvent) -> None:
        """Restore after Qt assigns the first non-zero comparison viewport."""
        super().showEvent(event)
        self._restore_inspection_after_mount()

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Complete a deferred initial restore after layout establishes geometry."""
        super().resizeEvent(event)
        self._restore_inspection_after_mount()

    def _present_comparison(self, comparison: CanvasComparison) -> None:
        """Select one comparison pair without replacing the QPane renderer."""
        self._ensure_catalog_source(comparison.primary_id)
        self._ensure_catalog_source(comparison.secondary_id)
        self._pane.setLinkedImageGroups(self._comparison_groups(comparison))
        self._pane.setComparisonSplit(
            comparison.split_position,
            comparison.orientation,
        )
        self._pane.setComparisonPair(
            comparison.primary_id,
            comparison.secondary_id,
        )

    def _ensure_catalog_source(
        self,
        composition_id: uuid.UUID,
    ) -> None:
        """Register one document composition once in the persistent catalog."""
        self._catalog.ensure(composition_id)

    def _comparison_groups(
        self,
        comparison: CanvasComparison,
    ) -> tuple[LinkedGroup, ...]:
        """Return the role-local linked group required by one reveal scene."""
        target_ids = {comparison.primary_id, comparison.secondary_id}
        groups = tuple(
            LinkedGroup(group.group_id, group.members)
            for group in self._session.inspection.groups()
            if set(group.members) == target_ids
        )
        if groups:
            return groups
        group = LinkedGroup(
            group_id=uuid.uuid4(),
            members=(comparison.primary_id, comparison.secondary_id),
        )
        self._session.inspection.replace_groups((group,))
        return (group,)

    def _title(self, composition_id: uuid.UUID) -> str:
        """Return the current document title for one catalog resource."""
        return self._document.resources.compositions.record(composition_id).title

    def _comparison_changed(self, state: object) -> None:
        """Persist native divider movement through the document presentation owner."""
        if not bool(getattr(state, "enabled", False)):
            return
        orientation = getattr(state, "orientation", None)
        position = getattr(state, "split_position", None)
        if not isinstance(orientation, ComparisonOrientation):
            return
        if not isinstance(position, float):
            return
        if (
            position == self._comparison.split_position
            and orientation is self._comparison.orientation
        ):
            return
        self._comparison = CanvasComparison(
            self._comparison.primary_id,
            self._comparison.secondary_id,
            position,
            orientation,
        )
        self._changed(position, orientation)

    def _draw_overlay(
        self,
        name: str,
        painter: object,
        state: object,
    ) -> None:
        """Translate native divider state into the CuteCanvas overlay contract."""

        draw_fn = self._comparison_overlays.get(name)
        if (
            draw_fn is None
            or not isinstance(painter, QPainter)
            or not isinstance(state, SceneSnapshotOverlayState)
        ):
            return
        draw_fn(
            painter,
            CanvasComparisonOverlayState(
                comparison=self._comparison,
                divider=CanvasComparisonDivider.from_comparison_state(
                    self._pane.comparisonDividerState()
                ),
                viewport=state.qpane_rect,
                primary_scale=self._display_scale(
                    state,
                    self._comparison.primary_id,
                ),
                secondary_scale=self._display_scale(
                    state,
                    self._comparison.secondary_id,
                ),
            ),
        )

    def _display_scale(
        self,
        state: SceneSnapshotOverlayState,
        composition_id: uuid.UUID,
    ) -> CanvasComparisonScale:
        """Return one rendered layer's physical source-pixel scale."""

        layer = next(
            (
                candidate
                for candidate in state.layers
                if candidate.source_id == composition_id and candidate.visible
            ),
            None,
        )
        if layer is None:
            return CanvasComparisonScale(0.0, 0.0)
        transform = layer.transform
        device_pixel_ratio = max(1.0, self._pane.devicePixelRatioF())
        return CanvasComparisonScale(
            hypot(transform.m11(), transform.m12()) * device_pixel_ratio,
            hypot(transform.m21(), transform.m22()) * device_pixel_ratio,
        )

    def _zoom_changed(self, zoom: float) -> None:
        """Expose only pointer-originated native zoom through CuteCanvas."""

        position = self._zoom_gesture_position
        self._zoom_gesture_position = None
        if position is not None:
            self._zoom_gesture(CanvasComparisonZoomGesture(position, float(zoom)))

    def _restore_inspection_after_mount(self) -> None:
        """Project persisted inspection only against final native viewport geometry."""
        if (
            self._inspection_restored
            or self._pane.width() <= 0
            or self._pane.height() <= 0
        ):
            return
        self._inspection_restored = True
        self._pane.restoreCatalogInspection()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Forward comparison interactions through CuteCanvas-owned boundaries."""
        if (
            watched is self._pane
            and event.type() is QEvent.Type.ContextMenu
            and isinstance(event, QContextMenuEvent)
        ):
            self._context_requested(
                self._comparison.primary_id,
                event.globalPos(),
            )
        if watched is self._pane and event.type() in {
            QEvent.Type.Wheel,
            QEvent.Type.MouseButtonDblClick,
        }:
            position = _pointer_position(event)
            if position is not None:
                self._zoom_gesture_position = position
        elif watched is self._pane and event.type() is QEvent.Type.MouseMove:
            position = _pointer_position(event)
            if position is not None:
                self._pointer_moved(position)
        return super().eventFilter(watched, event)


def _pointer_position(event: QEvent) -> QPointF | None:
    """Return one QPane-local position from a supported pointer event."""

    if isinstance(event, (QMouseEvent, QWheelEvent)):
        return QPointF(event.position())
    return None
