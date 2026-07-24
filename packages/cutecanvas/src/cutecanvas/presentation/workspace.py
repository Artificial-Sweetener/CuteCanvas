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

from PySide6.QtCore import QRectF, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QStackedLayout, QWidget
from qpane.sdk.types import ComparisonOrientation, LinkedGroup
from qpane.sdk.ui import OutboundMimeProvider

from ..canvas import CuteCanvas
from ..document import (
    CanvasComparison,
    CanvasDocument,
    CanvasPresentation,
    CanvasPresentationKind,
    CanvasSessionSnapshot,
    CanvasViewSession,
)
from ..editor.interaction_policy import CanvasInteractionMode
from ..facade.drag_api import CanvasDragSubjectResolver
from .contracts import CanvasPresentationContext, CanvasPresentationProvider
from .surfaces import (
    CanvasTargetMount,
    IndependentCanvasComparison,
    ResponsiveCanvasGrid,
    TabbedCanvasSurface,
)


class CanvasWorkspace(QWidget):
    """Present one host-owned document through interchangeable view arrangements."""

    presentationChanged = Signal(object)
    """Emit the immutable presentation after the visible surface changes."""

    def __init__(
        self,
        *,
        document: CanvasDocument | None = None,
        session: CanvasViewSession | None = None,
        features: Iterable[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Create a workspace while preserving document and session ownership."""
        super().__init__(parent)
        self._document = document or CanvasDocument()
        self._owns_document = document is None
        self._session = session or CanvasViewSession()
        self._features = None if features is None else tuple(features)
        self._providers: dict[str, CanvasPresentationProvider] = {}
        self._canvases: dict[uuid.UUID, CuteCanvas] = {}
        self._mounts: dict[uuid.UUID, CanvasTargetMount] = {}
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
        self.destroyed.connect(lambda _obj=None: self._close_owners())

    @property
    def document(self) -> CanvasDocument:
        """Return the headless document mounted by this workspace."""
        return self._document

    @property
    def session(self) -> CanvasViewSession:
        """Return detachable presentation and inspection state."""
        return self._session

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
        *,
        linked: bool = True,
    ) -> None:
        """Show switchable composition views with optional linked inspection."""
        target_ids = tuple(composition_ids)
        self._set_presentation(
            CanvasPresentation(
                CanvasPresentationKind.TABBED,
                target_ids,
                linked_inspection=linked,
            )
        )

    def setGridPresentation(
        self,
        composition_ids: Iterable[uuid.UUID],
        *,
        linked: bool = False,
    ) -> None:
        """Show a responsive grid of independent composition targets."""
        target_ids = tuple(composition_ids)
        self._set_presentation(
            CanvasPresentation(
                CanvasPresentationKind.GRID,
                target_ids,
                linked_inspection=linked,
            )
        )

    def setComparisonPresentation(
        self,
        primary_id: uuid.UUID,
        secondary_id: uuid.UUID,
        *,
        split_position: float = 0.5,
        orientation: ComparisonOrientation = ComparisonOrientation.VERTICAL,
        linked: bool = True,
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
                linked,
            )
        )

    def setCustomPresentation(
        self,
        provider_id: str,
        composition_ids: Iterable[uuid.UUID],
        *,
        linked: bool = False,
    ) -> None:
        """Build one registered host surface over validated document targets."""
        if provider_id not in self._providers:
            raise KeyError(f"unknown presentation provider: {provider_id}")
        self._set_presentation(
            CanvasPresentation(
                CanvasPresentationKind.CUSTOM,
                tuple(composition_ids),
                linked_inspection=linked,
                provider_id=provider_id,
            )
        )

    def currentCanvas(self) -> CuteCanvas | None:
        """Return the canvas receiving focused interaction, if mounted."""
        target_id = self._session.active_composition_id
        return None if target_id is None else self._canvases.get(target_id)

    def canvasFor(self, composition_id: uuid.UUID) -> CuteCanvas | None:
        """Return a mounted target canvas without creating parallel state."""
        return self._canvases.get(composition_id)

    def setOutboundMimeProvider(
        self,
        provider: OutboundMimeProvider,
        *,
        subject_resolver: CanvasDragSubjectResolver | None = None,
    ) -> None:
        """Apply host MIME policy to current and future presentation targets."""
        self._outbound_mime_provider = provider
        self._drag_subject_resolver = subject_resolver
        for canvas in self._canvases.values():
            canvas.setOutboundMimeProvider(
                provider,
                subject_resolver=subject_resolver,
            )

    def clearOutboundMimeProvider(self) -> None:
        """Disable and cancel outbound dragging on every mounted target."""
        self._outbound_mime_provider = None
        self._drag_subject_resolver = None
        for canvas in self._canvases.values():
            canvas.clearOutboundMimeProvider()

    def setInteractionMode(self, mode: CanvasInteractionMode) -> None:
        """Apply one capability profile to current and future target canvases."""
        resolved = CanvasInteractionMode(mode)
        if resolved is CanvasInteractionMode.CUSTOM:
            raise ValueError("custom workspace policy must be applied per canvas")
        self._interaction_mode = resolved
        for canvas in self._canvases.values():
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
        """Update a divider in place when its target arrangement is unchanged."""
        previous = self._applied_presentation
        surface = self._surface
        comparison = presentation.comparison
        if (
            previous is None
            or surface is None
            or comparison is None
            or presentation.kind is not CanvasPresentationKind.COMPARISON
            or previous.kind is not CanvasPresentationKind.COMPARISON
            or previous.target_ids != presentation.target_ids
            or previous.linked_inspection != presentation.linked_inspection
            or previous.comparison is None
            or previous.comparison.orientation is not comparison.orientation
            or not isinstance(surface, IndependentCanvasComparison)
        ):
            return False
        surface.set_split(comparison.split_position)
        return True

    def _rebuild(self, presentation: CanvasPresentation) -> None:
        """Replace only presentation widgets while retaining target renderers."""
        self._configure_linking(presentation)
        previous = self._surface
        surface = self._build_surface(presentation)
        self._surface = surface
        self._applied_presentation = presentation
        self._layout.addWidget(surface)
        self._layout.setCurrentWidget(surface)
        if previous is not None:
            self._layout.removeWidget(previous)
            previous.setParent(None)
            previous.deleteLater()
        self.presentationChanged.emit(presentation)

    def _build_surface(self, presentation: CanvasPresentation) -> QWidget:
        """Create one small surface around reusable composition canvases."""
        entries = tuple(
            (
                target_id,
                self._title(target_id),
                self._mount(target_id, self),
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
            return ResponsiveCanvasGrid(grid_entries, self)
        if presentation.kind is CanvasPresentationKind.COMPARISON:
            comparison = presentation.comparison
            if comparison is None:
                raise RuntimeError("comparison presentation has no state")
            return IndependentCanvasComparison(
                entries[0][2],
                entries[1][2],
                split_position=comparison.split_position,
                orientation=comparison.orientation,
                split_changed=self._set_comparison_split,
                parent=self,
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
                self._canvas,
            ),
            self,
        )

    def _ensure_canvas(self, target_id: uuid.UUID) -> CuteCanvas:
        """Return one retained renderer without changing its QWidget parent."""
        canvas = self._canvases.get(target_id)
        if canvas is None:
            child_session = CanvasViewSession(
                inspection=self._session.inspection,
            )
            canvas = CuteCanvas(
                document=self._document,
                session=child_session,
                features=self._features,
            )
            self._canvases[target_id] = canvas
            self._mounts[target_id] = CanvasTargetMount(canvas, self)
            child_session.activate(
                target_id,
                available_ids=self._available_ids(),
            )
            canvas.openComposition(target_id)
            canvas.setInteractionMode(self._interaction_mode)
            canvas.setControlMode(canvas.CONTROL_MODE_PANZOOM)
            if self._outbound_mime_provider is not None:
                canvas.setOutboundMimeProvider(
                    self._outbound_mime_provider,
                    subject_resolver=self._drag_subject_resolver,
                )
        return canvas

    def _mount(
        self,
        target_id: uuid.UUID,
        parent: QWidget,
    ) -> CanvasTargetMount:
        """Move only a lightweight host between built-in presentation surfaces."""
        canvas = self._ensure_canvas(target_id)
        mount = self._mounts[target_id]
        if canvas.parent() is not mount:
            canvas.setParent(mount)
            canvas.setGeometry(mount.rect())
            canvas.show()
        mount.setParent(parent)
        mount.show()
        return mount

    def _canvas(self, target_id: uuid.UUID, parent: QWidget) -> CuteCanvas:
        """Give a custom provider a retained canvas under its chosen parent."""
        canvas = self._ensure_canvas(target_id)
        canvas.setParent(parent)
        canvas.show()
        return canvas

    def _activate(self, target_id: uuid.UUID) -> None:
        """Activate one visible target in workspace session state."""
        self._session.activate(
            target_id,
            available_ids=self._available_ids(),
        )

    def _set_comparison_split(self, position: float) -> None:
        """Replace only transient comparison state during divider movement."""
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
                    comparison.orientation,
                ),
                presentation.linked_inspection,
            )
        )

    def _configure_linking(self, presentation: CanvasPresentation) -> None:
        """Apply one workspace-owned link group without document mutations."""
        if presentation.linked_inspection and len(presentation.target_ids) >= 2:
            existing = self._session.inspection.groups()
            group_id = existing[0].group_id if len(existing) == 1 else uuid.uuid4()
            self._session.inspection.replace_groups(
                (LinkedGroup(group_id, presentation.target_ids),)
            )
            return
        self._session.inspection.replace_groups(())

    def _reconcile_document(self) -> None:
        """Remove unavailable presentation targets after document mutations."""
        self._session.reconcile(self._available_ids())

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
        self._session_unsubscribe()
        self._document_unsubscribe()
        for canvas in tuple(self._canvases.values()):
            try:
                canvas.close()
                canvas.deleteLater()
            except RuntimeError:
                pass
        self._canvases.clear()
        self._mounts.clear()
        if self._owns_document:
            self._document.close()
