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
"""Direct translation of pixel-selection coverage without moving content."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace

from cutecanvas.coverage.containment import coverage_contains
from cutecanvas.coverage.document import CoverageDocument
from cutecanvas.coverage.surface import CoverageSnapshot
from PySide6.QtCore import QPointF
from qpane.sdk.scene import LayerTransform, SceneDescriptor

from .service import PixelSelectionService


@dataclass(slots=True)
class _SelectionTranslationSession:
    """Retain one immutable selection origin and its current preview."""

    scene_id: uuid.UUID
    origin: QPointF
    before_document: CoverageDocument
    before_coverage: CoverageSnapshot
    current_document: CoverageDocument
    delta: tuple[int, int] = (0, 0)


class PixelSelectionTranslationInteraction:
    """Preview and commit selection-boundary translation as one history edit."""

    def __init__(
        self,
        *,
        active_scene: Callable[[], SceneDescriptor | None],
        selections: PixelSelectionService,
    ) -> None:
        """Bind the active-scene provider and authoritative selection owner."""
        self._active_scene = active_scene
        self._selections = selections
        self._session: _SelectionTranslationSession | None = None

    @property
    def active(self) -> bool:
        """Return whether a boundary-translation gesture owns pointer input."""
        return self._session is not None

    def can_begin(self, scene_point: QPointF) -> bool:
        """Return whether ``scene_point`` lies inside the active selection."""
        scene = self._active_scene()
        if scene is None:
            return False
        coverage = self._selections.state(scene.scene_id).coverage
        return coverage is not None and coverage_contains(coverage, scene_point)

    def begin(self, scene_point: QPointF) -> bool:
        """Capture a selection translation when the press is inside coverage."""
        if self._session is not None:
            return False
        scene = self._active_scene()
        if scene is None:
            return False
        state = self._selections.state(scene.scene_id)
        document = self._selections.document(scene.scene_id)
        coverage = state.coverage
        if (
            document is None
            or coverage is None
            or not coverage_contains(coverage, scene_point)
        ):
            return False
        self._session = _SelectionTranslationSession(
            scene_id=scene.scene_id,
            origin=QPointF(scene_point),
            before_document=document,
            before_coverage=coverage,
            current_document=document,
        )
        return True

    def update(self, scene_point: QPointF) -> bool:
        """Publish one zero-copy coverage preview relative to the press origin."""
        session = self._session
        if session is None:
            return False
        if self._selections.document(session.scene_id) != session.current_document:
            self._session = None
            return False
        delta = (
            round(scene_point.x() - session.origin.x()),
            round(scene_point.y() - session.origin.y()),
        )
        if delta == session.delta:
            return False
        document = _translated_document(session.before_document, *delta)
        coverage = session.before_coverage.translated(*delta)
        changed = self._selections.preview_document(
            session.scene_id,
            document,
            coverage=coverage,
        )
        if changed:
            session.current_document = document
            session.delta = delta
        return changed

    def finish(self, scene_point: QPointF) -> bool:
        """Commit the final preview to history without touching layer pixels."""
        session = self._session
        if session is None:
            return False
        self.update(scene_point)
        session = self._session
        self._session = None
        if session is None:
            return True
        self._selections.record_preview(session.scene_id, session.before_document)
        return True

    def cancel(self) -> bool:
        """Restore the pre-gesture selection without recording history."""
        session = self._session
        if session is None:
            return False
        self._session = None
        if self._selections.document(session.scene_id) != session.current_document:
            return True
        self._selections.restore_document(
            session.scene_id,
            session.before_document,
            coverage=session.before_coverage,
        )
        return True

    def suspend(self) -> bool:
        """Cancel an unresolved preview when tool ownership changes."""
        return self.cancel()


def _translated_document(
    document: CoverageDocument,
    delta_x: int,
    delta_y: int,
) -> CoverageDocument:
    """Return retained authorship translated without evaluating its pixels."""
    if delta_x == 0 and delta_y == 0:
        return document
    translation = LayerTransform(dx=float(delta_x), dy=float(delta_y))
    items = tuple(
        replace(
            item,
            transform=item.transform.followed_by(translation),
        )
        for item in document.items
    )
    return replace(
        document,
        items=items,
        revision=document.revision + 1,
        evaluation_token=uuid.uuid4(),
    )
