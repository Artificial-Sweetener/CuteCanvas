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
"""Host-facing document workspace for built-in and custom presentations."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import cast

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QStackedLayout, QWidget

from qpane.sdk.execution import (
    DefaultExecutionPolicy,
    ExecutionRuntime,
)
from qpane.sdk.layout import ResponsiveGridPolicy, ResponsiveGridSnapshot
from qpane.sdk.types import ComparisonOrientation
from qpane.sdk.ui import OutboundMimeProvider

from ..canvas import CuteCanvas
from ..document import (
    CanvasComparison,
    CanvasDocument,
    CanvasInspectionGroup,
    CanvasPresentation,
    CanvasPresentationKind,
    CanvasSessionSnapshot,
    CanvasViewSession,
)
from ..editor.interaction_policy import CanvasInteractionMode
from ..facade.drag_api import CanvasDragSubjectResolver
from ..runtime.document_runtime import CanvasDocumentRuntime
from .comparison_overlays import CanvasComparisonOverlayDrawFn
from .contracts import CanvasPresentationContext, CanvasPresentationProvider
from .grid_surface import ResponsiveCanvasGrid
from .native_comparison import NativeCanvasComparison
from .surfaces import TabbedCanvasSurface
from .target_mount import CanvasTargetMount
from .target_pool import CanvasTargetPool, CanvasViewKey
from .widget_lifetime import WidgetOwnerLifetimeGuard


class CanvasWorkspace(QWidget):
    """Present one host-owned document through interchangeable view arrangements."""

    presentationChanged = Signal(object)
    """Emit the immutable presentation after the visible surface changes."""

    targetActivated = Signal(object)
    """Emit the composition UUID selected through an interactive presentation."""

    outboundDragFailed = Signal(object, str)
    """Emit a target canvas's stable drag subject and materialization message."""

    contentContextRequested = Signal(object, object)
    """Emit a target canvas's stable content subject and global context position."""

    comparisonZoomGesture = Signal(object)
    """Emit a pointer-originated comparison zoom through a renderer-free value."""

    comparisonPointerMoved = Signal(object)
    """Emit a native comparison pointer position in workspace-local coordinates."""

    def __init__(
        self,
        *,
        document: CanvasDocument | None = None,
        session: CanvasViewSession | None = None,
        features: Iterable[str] | None = None,
        document_runtime: CanvasDocumentRuntime | None = None,
        execution_runtime: ExecutionRuntime | None = None,
        execution_policy: DefaultExecutionPolicy | None = None,
        retained_target_capacity: int = 16,
        parent: QWidget | None = None,
    ) -> None:
        """Create a workspace over one runtime shared by every target canvas.

        Args:
            retained_target_capacity: Maximum hidden role-target renderers kept
                for fast presentation switching. Visible targets are additional.
        """
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        if document_runtime is not None and (
            execution_runtime is not None or execution_policy is not None
        ):
            raise ValueError(
                "document_runtime cannot be combined with execution runtime options"
            )
        if execution_runtime is not None and execution_policy is not None:
            raise ValueError(
                "execution_policy cannot configure a host-owned execution_runtime"
            )
        if document_runtime is not None:
            if document is not None and document_runtime.document is not document:
                raise ValueError("document_runtime belongs to a different document")
            self._document = document_runtime.document
            self._document_runtime = document_runtime
            self._owns_document_runtime = False
        else:
            self._document = document or CanvasDocument()
            self._document_runtime = CanvasDocumentRuntime(
                self._document,
                execution_runtime=execution_runtime,
                execution_policy=execution_policy,
            )
            self._owns_document_runtime = True
        self._owns_document = document is None and document_runtime is None
        self._session = session or CanvasViewSession()
        self._features = None if features is None else tuple(features)
        self._providers: dict[str, CanvasPresentationProvider] = {}
        self._targets = CanvasTargetPool(
            self,
            create_canvas=self._create_target_canvas,
            inactive_capacity=retained_target_capacity,
        )
        self._role_sessions: dict[CanvasPresentationKind, CanvasViewSession] = {}
        self._comparison_inspection_groups: tuple[CanvasInspectionGroup, ...] = ()
        self._comparison_overlays: dict[str, CanvasComparisonOverlayDrawFn] = {}
        self._comparison_surface_captured_for_group_change: (
            NativeCanvasComparison | None
        ) = None
        self._outbound_mime_provider: OutboundMimeProvider | None = None
        self._drag_subject_resolver: CanvasDragSubjectResolver | None = None
        self._interaction_mode = CanvasInteractionMode.READ_ONLY
        self._surface: QWidget | None = None
        self._applied_presentation: CanvasPresentation | None = None
        self._closed = False
        self._layout = QStackedLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._session_unsubscribe = self._session.subscribe(self._session_changed)
        self._document_unsubscribe = self._document.events.subscribe(
            lambda _change: self._reconcile_document()
        )
        self._lifetime_guard = WidgetOwnerLifetimeGuard(self, self._close_owners)

    @property
    def document(self) -> CanvasDocument:
        """Return the headless document mounted by this workspace."""
        return self._document

    @property
    def session(self) -> CanvasViewSession:
        """Return detachable presentation and inspection state."""
        return self._session

    @property
    def documentRuntime(self) -> CanvasDocumentRuntime:
        """Return the document-wide execution owner shared by target views."""
        return self._document_runtime

    def registerPresentationProvider(
        self,
        provider: CanvasPresentationProvider,
    ) -> None:
        """Register one stable host presentation provider."""
        provider_id = provider.presentation_id.strip()
        if not provider_id:
            raise ValueError("presentation_id must not be empty")
        if provider_id in self._providers:
            raise ValueError(f"presentation provider already exists: {provider_id}")
        self._providers[provider_id] = provider

    def setSinglePresentation(self, composition_id: uuid.UUID) -> None:
        """Show one composition in its native coordinate space."""
        self._set_presentation(
            CanvasPresentation(
                CanvasPresentationKind.SINGLE,
                (composition_id,),
            )
        )

    def setTabbedPresentation(
        self,
        composition_ids: Iterable[uuid.UUID],
    ) -> None:
        """Show switchable composition views with host-owned inspection state."""
        target_ids = tuple(composition_ids)
        self._set_presentation(
            CanvasPresentation(
                CanvasPresentationKind.TABBED,
                target_ids,
            )
        )

    def setGridPresentation(
        self,
        composition_ids: Iterable[uuid.UUID],
        *,
        policy: ResponsiveGridPolicy | None = None,
    ) -> None:
        """Show a responsive grid of independent composition targets.

        Args:
            composition_ids: Ordered document compositions to present.
            policy: Source-neutral responsive layout policy for this grid.
        """
        target_ids = tuple(composition_ids)
        self._set_presentation(
            CanvasPresentation(
                CanvasPresentationKind.GRID,
                target_ids,
                grid_policy=policy,
            )
        )

    def gridSnapshot(self) -> ResponsiveGridSnapshot | None:
        """Return the current grid's immutable QPane layout snapshot, if any."""
        surface = self._surface
        return surface.snapshot if isinstance(surface, ResponsiveCanvasGrid) else None

    def setInspectionGroups(self, groups: Iterable[CanvasInspectionGroup]) -> None:
        """Replace host-owned linked inspection groups for detail presentations."""

        resolved_groups = tuple(groups)
        self._session.setInspectionGroups(resolved_groups)

    def setComparisonInspectionGroups(
        self,
        groups: Iterable[CanvasInspectionGroup],
    ) -> None:
        """Replace linked inspection groups used exclusively by comparison views."""

        resolved_groups = tuple(groups)
        if resolved_groups == self._comparison_inspection_groups:
            return
        surface = self._surface
        if isinstance(surface, NativeCanvasComparison):
            surface.release()
            self._comparison_surface_captured_for_group_change = surface
        self._comparison_inspection_groups = resolved_groups
        comparison_session = self._role_sessions.get(CanvasPresentationKind.COMPARISON)
        if comparison_session is not None:
            comparison_session.setInspectionGroups(resolved_groups)

    def setComparisonPresentation(
        self,
        primary_id: uuid.UUID,
        secondary_id: uuid.UUID,
        *,
        split_position: float = 0.5,
        orientation: ComparisonOrientation = ComparisonOrientation.VERTICAL,
    ) -> None:
        """Reveal two independent composition views across one divider."""
        comparison = CanvasComparison(
            primary_id,
            secondary_id,
            split_position,
            orientation,
        )
        self._set_presentation(
            CanvasPresentation(
                CanvasPresentationKind.COMPARISON,
                (primary_id, secondary_id),
                comparison,
            )
        )

    def setCustomPresentation(
        self,
        provider_id: str,
        composition_ids: Iterable[uuid.UUID],
    ) -> None:
        """Build one registered host surface over validated document targets."""
        if provider_id not in self._providers:
            raise KeyError(f"unknown presentation provider: {provider_id}")
        self._set_presentation(
            CanvasPresentation(
                CanvasPresentationKind.CUSTOM,
                tuple(composition_ids),
                provider_id=provider_id,
            )
        )

    def currentCanvas(self) -> QWidget | None:
        """Return the native widget receiving focused interaction, if mounted."""

        surface = self._surface
        if isinstance(surface, NativeCanvasComparison):
            return cast(QWidget, surface.pane)
        target_id = self._session.active_composition_id
        return None if target_id is None else self.canvasFor(target_id)

    def registerComparisonOverlay(
        self,
        name: str,
        draw_fn: CanvasComparisonOverlayDrawFn,
    ) -> None:
        """Paint host artwork over every current and future native comparison."""

        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("comparison overlay name must not be blank")
        if normalized_name in self._comparison_overlays:
            raise ValueError(f"comparison overlay already exists: {normalized_name}")
        self._comparison_overlays[normalized_name] = draw_fn
        surface = self._surface
        if isinstance(surface, NativeCanvasComparison):
            surface.registerOverlay(normalized_name, draw_fn)

    def unregisterComparisonOverlay(self, name: str) -> None:
        """Remove one host comparison overlay from current and future surfaces."""

        if self._comparison_overlays.pop(name, None) is None:
            return
        surface = self._surface
        if isinstance(surface, NativeCanvasComparison):
            surface.unregisterOverlay(name)

    def refreshComparisonOverlays(self) -> None:
        """Request a comparison overlay repaint without exposing the renderer."""

        surface = self._surface
        if isinstance(surface, NativeCanvasComparison):
            surface.refreshOverlays()

    def canvasFor(self, composition_id: uuid.UUID) -> CuteCanvas | None:
        """Return a current canvas first, or a retained role-specific canvas."""

        active_role = self._presentation_view_role(self._session.presentation)
        return self._targets.canvas_for(
            composition_id,
            preferred_role=active_role,
        )

    def setOutboundMimeProvider(
        self,
        provider: OutboundMimeProvider,
        *,
        subject_resolver: CanvasDragSubjectResolver | None = None,
    ) -> None:
        """Apply host MIME policy to current and future presentation targets."""
        self._outbound_mime_provider = provider
        self._drag_subject_resolver = subject_resolver
        for canvas in self._targets.values():
            canvas.setOutboundMimeProvider(
                provider,
                subject_resolver=subject_resolver,
            )

    def clearOutboundMimeProvider(self) -> None:
        """Disable and cancel outbound dragging on every mounted target."""
        self._outbound_mime_provider = None
        self._drag_subject_resolver = None
        for canvas in self._targets.values():
            canvas.clearOutboundMimeProvider()

    def setInteractionMode(self, mode: CanvasInteractionMode) -> None:
        """Apply one capability profile to current and future target canvases."""
        resolved = CanvasInteractionMode(mode)
        if resolved is CanvasInteractionMode.CUSTOM:
            raise ValueError("custom workspace policy must be applied per canvas")
        self._interaction_mode = resolved
        for canvas in self._targets.values():
            canvas.setInteractionMode(resolved)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Release mounted view owners when the workspace closes."""
        self._close_owners()
        super().closeEvent(event)

    def _set_presentation(self, presentation: CanvasPresentation) -> None:
        """Validate targets and install immutable session presentation state."""
        self._session.set_presentation(
            presentation,
            available_ids=self._available_ids(),
        )

    def _session_changed(self, snapshot: CanvasSessionSnapshot) -> None:
        """Apply changed arrangement or focus without touching document history."""
        if self._update_comparison_surface(snapshot.presentation):
            self._applied_presentation = snapshot.presentation
            self.presentationChanged.emit(snapshot.presentation)
        elif snapshot.presentation != self._applied_presentation:
            self._rebuild(snapshot.presentation)
        surface = self._surface
        activate = getattr(surface, "activate", None)
        if callable(activate):
            activate(snapshot.active_composition_id)

    def _update_comparison_surface(
        self,
        presentation: CanvasPresentation,
    ) -> bool:
        """Apply any comparison pair through the persistent native renderer."""
        previous = self._applied_presentation
        surface = self._surface
        comparison = presentation.comparison
        if (
            previous is None
            or surface is None
            or comparison is None
            or presentation.kind is not CanvasPresentationKind.COMPARISON
            or previous.kind is not CanvasPresentationKind.COMPARISON
            or previous.comparison is None
            or not isinstance(surface, NativeCanvasComparison)
        ):
            return False
        captured_for_group_change = (
            surface is self._comparison_surface_captured_for_group_change
        )
        surface.setComparison(
            comparison,
            capture_current=not captured_for_group_change,
        )
        if captured_for_group_change:
            self._comparison_surface_captured_for_group_change = None
        return True

    def _rebuild(self, presentation: CanvasPresentation) -> None:
        """Replace only presentation widgets while retaining target renderers."""
        previous = self._surface
        if (
            isinstance(previous, NativeCanvasComparison)
            and previous is not self._comparison_surface_captured_for_group_change
        ):
            previous.release()
        if previous is self._comparison_surface_captured_for_group_change:
            self._comparison_surface_captured_for_group_change = None
        surface = self._build_surface(presentation)
        self._configure_target_interaction(presentation)
        self._surface = surface
        self._applied_presentation = presentation
        self._layout.addWidget(surface)
        self._layout.setCurrentWidget(surface)
        if isinstance(surface, ResponsiveCanvasGrid):
            surface.applyResponsiveGeometry()
        self._targets.activate(self._required_target_keys(presentation))
        if previous is not None and previous is not surface:
            if isinstance(previous, ResponsiveCanvasGrid):
                previous.release()
            self._layout.removeWidget(previous)
            if not self._targets.contains_mount(previous) and not surface.isAncestorOf(
                previous
            ):
                previous.setParent(None)
                previous.deleteLater()
        self.presentationChanged.emit(presentation)

    def _build_surface(self, presentation: CanvasPresentation) -> QWidget:
        """Create one small surface around reusable composition canvases."""
        if presentation.kind is CanvasPresentationKind.COMPARISON:
            comparison = presentation.comparison
            if comparison is None:
                raise RuntimeError("comparison presentation has no state")
            return NativeCanvasComparison(
                document=self._document,
                document_runtime=self._document_runtime,
                session=self._session_for_view_role(CanvasPresentationKind.COMPARISON),
                comparison=comparison,
                changed=self._set_comparison_split,
                context_requested=self._request_native_comparison_context,
                zoom_gesture=self.comparisonZoomGesture.emit,
                pointer_moved=self.comparisonPointerMoved.emit,
                overlays=self._comparison_overlays,
                parent=self,
            )
        view_role = self._presentation_view_role(presentation)
        entries = tuple(
            (
                target_id,
                self._title(target_id),
                self._mount(target_id, self, view_role=view_role),
            )
            for target_id in presentation.target_ids
        )
        if presentation.kind is CanvasPresentationKind.SINGLE:
            if not entries:
                return QWidget(self)
            return entries[0][2]
        if presentation.kind is CanvasPresentationKind.TABBED:
            return TabbedCanvasSurface(
                entries,
                self._activate,
                self,
            )
        if presentation.kind is CanvasPresentationKind.GRID:
            grid_entries = tuple(
                (
                    target_id,
                    QRectF(
                        self._document.resources.compositions.record(
                            target_id
                        ).canvas_bounds
                    ),
                    canvas,
                )
                for target_id, _title, canvas in entries
            )
            return ResponsiveCanvasGrid(
                grid_entries,
                self,
                policy=presentation.grid_policy,
                activated=self._activate,
            )
        provider_id = presentation.provider_id
        provider = None if provider_id is None else self._providers.get(provider_id)
        if provider is None:
            raise RuntimeError("custom presentation provider is unavailable")
        return provider.create_widget(
            CanvasPresentationContext(
                self._document,
                self._session,
                presentation.target_ids,
                lambda target_id, parent: self._canvas(
                    target_id,
                    parent,
                    view_role=view_role,
                ),
            ),
            self,
        )

    def _configure_target_interaction(
        self,
        presentation: CanvasPresentation,
    ) -> None:
        """Give grid targets drag/click ownership instead of viewport navigation."""

        grid_target = presentation.kind is CanvasPresentationKind.GRID
        if presentation.kind is CanvasPresentationKind.COMPARISON:
            return
        control_mode = (
            CuteCanvas.CONTROL_MODE_CURSOR
            if grid_target
            else CuteCanvas.CONTROL_MODE_PANZOOM
        )
        for target_id in presentation.target_ids:
            canvas = self._targets.canvas_for(
                target_id,
                preferred_role=self._presentation_view_role(presentation),
            )
            if canvas is None:
                continue
            canvas.setPanZoomLocked(False)
            canvas.setControlMode(control_mode)

    @classmethod
    def _required_target_keys(
        cls,
        presentation: CanvasPresentation,
    ) -> tuple[CanvasViewKey, ...]:
        """Return the only heavyweight target views needed by a presentation."""

        if presentation.kind is CanvasPresentationKind.COMPARISON:
            return ()
        role = cls._presentation_view_role(presentation)
        return tuple((role, target_id) for target_id in presentation.target_ids)

    @staticmethod
    def _presentation_view_role(
        presentation: CanvasPresentation,
    ) -> CanvasPresentationKind:
        """Return the independent viewport role required by one presentation."""

        if presentation.kind is CanvasPresentationKind.GRID:
            return CanvasPresentationKind.GRID
        if presentation.kind is CanvasPresentationKind.COMPARISON:
            return CanvasPresentationKind.COMPARISON
        return CanvasPresentationKind.SINGLE

    def _create_target_canvas(
        self,
        target_id: uuid.UUID,
        view_role: CanvasPresentationKind,
    ) -> CuteCanvas:
        """Create and configure one renderer requested by the target pool."""

        child_session = CanvasViewSession(
            inspection=self._session_for_view_role(view_role).inspection,
        )
        canvas = CuteCanvas(
            document=self._document,
            session=child_session,
            features=self._features,
            document_runtime=self._document_runtime,
        )
        canvas.outboundDragFailed.connect(self.outboundDragFailed.emit)
        canvas.contentContextRequested.connect(self.contentContextRequested.emit)
        canvas.openComposition(target_id)
        canvas.setInteractionMode(self._interaction_mode)
        if self._outbound_mime_provider is not None:
            canvas.setOutboundMimeProvider(
                self._outbound_mime_provider,
                subject_resolver=self._drag_subject_resolver,
            )
        return canvas

    def _session_for_view_role(
        self,
        view_role: CanvasPresentationKind,
    ) -> CanvasViewSession:
        """Return the inspection owner shared only by one presentation role."""

        if view_role is CanvasPresentationKind.SINGLE:
            return self._session
        session = self._role_sessions.get(view_role)
        if session is None:
            session = CanvasViewSession()
            if view_role is CanvasPresentationKind.COMPARISON:
                session.setInspectionGroups(self._comparison_inspection_groups)
            self._role_sessions[view_role] = session
        return session

    def _mount(
        self,
        target_id: uuid.UUID,
        parent: QWidget,
        *,
        view_role: CanvasPresentationKind,
    ) -> CanvasTargetMount:
        """Move only a lightweight host between built-in presentation surfaces."""
        return self._targets.mount(target_id, parent, view_role=view_role)

    def _canvas(
        self,
        target_id: uuid.UUID,
        parent: QWidget,
        *,
        view_role: CanvasPresentationKind,
    ) -> CuteCanvas:
        """Give a custom provider a retained canvas under its chosen parent."""
        return self._targets.direct_canvas(target_id, parent, view_role=view_role)

    def _activate(self, target_id: uuid.UUID) -> None:
        """Publish every deliberate selection of a visible workspace target."""

        if target_id not in self._available_ids():
            return
        self._session.activate(
            target_id,
            available_ids=self._available_ids(),
        )
        self.targetActivated.emit(target_id)

    def _request_native_comparison_context(
        self,
        composition_id: uuid.UUID,
        position: QPoint,
    ) -> None:
        """Expose a native comparison target through the workspace context signal."""
        self.contentContextRequested.emit(
            self._document.content_reference(composition_id),
            position,
        )

    def _set_comparison_split(
        self,
        position: float,
        orientation: ComparisonOrientation | None = None,
    ) -> None:
        """Replace only native divider state without rebuilding its render scene."""
        presentation = self._session.presentation
        comparison = presentation.comparison
        if comparison is None:
            return
        self._set_presentation(
            CanvasPresentation(
                CanvasPresentationKind.COMPARISON,
                presentation.target_ids,
                CanvasComparison(
                    comparison.primary_id,
                    comparison.secondary_id,
                    position,
                    comparison.orientation if orientation is None else orientation,
                ),
            )
        )

    def _reconcile_document(self) -> None:
        """Remove unavailable presentation targets after document mutations."""
        available_ids = self._available_ids()
        available = set(available_ids)
        for group in self._session.inspection.groups():
            for target_id in group.members:
                if target_id not in available:
                    self._session.inspection.discard(target_id)
        self._session.reconcile(available_ids)
        self._targets.retire_unavailable(available)

    def _available_ids(self) -> tuple[uuid.UUID, ...]:
        """Return current composition targets in document order."""
        return self._document.resources.compositions.composition_ids()

    def _title(self, composition_id: uuid.UUID) -> str:
        """Return the current host-facing title for one target."""
        return self._document.resources.compositions.record(composition_id).title

    def _close_owners(self) -> None:
        """Release subscriptions, view workflows, and optionally the document."""
        if self._closed:
            return
        self._closed = True
        self._lifetime_guard.detach()
        self._session_unsubscribe()
        self._document_unsubscribe()
        self._targets.close()
        surface = self._surface
        self._surface = None
        if surface is not None:
            try:
                surface.close()
                surface.setParent(None)
                surface.deleteLater()
            except RuntimeError:
                pass
        if self._owns_document_runtime:
            self._document_runtime.close()
        if self._owns_document:
            self._document.close()
