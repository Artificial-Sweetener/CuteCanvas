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
"""Composition pixel-selection adapter for the shared paint-target contract."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from cutecanvas.coverage import (
    CoverageCombineMode,
    CoverageDocument,
    CoverageItem,
    StrokeCoverageItem,
)
from PySide6.QtGui import QColor

from ..painting import (
    BrushCompositor,
    BrushPreset,
    BrushStrokeCompiler,
    BrushStrokeSegment,
    PaintTargetContext,
)
from ..painting.model import BrushOperation
from ..types import PaintTargetKind
from .service import PixelSelectionService


@dataclass(slots=True)
class _SelectionPaintSession:
    """Retain one unresolved selection-paint transition."""

    scene_id: uuid.UUID
    before: CoverageDocument | None
    item_id: uuid.UUID
    segments: tuple[BrushStrokeSegment, ...] = ()


class PixelSelectionPaintTargetOwner:
    """Paint the one authoritative pixel selection with shared brush dabs."""

    def __init__(
        self,
        selections: PixelSelectionService,
        compositor: BrushCompositor | None = None,
    ) -> None:
        """Bind authoritative selection state."""
        self._selections = selections
        self._compiler = BrushStrokeCompiler()
        self._compositor = BrushCompositor() if compositor is None else compositor
        self._session: _SelectionPaintSession | None = None

    def supports(self, target: PaintTargetContext) -> bool:
        """Return whether ``target`` is composition pixel-selection coverage."""
        return target.identity.kind is PaintTargetKind.PIXEL_SELECTION

    def begin(self, target: PaintTargetContext) -> bool:
        """Capture the exact pre-stroke selection state."""
        if self._session is not None:
            self.cancel(target)
        self._session = _SelectionPaintSession(
            target.scene.scene_id,
            self._selections.document(target.scene.scene_id),
            uuid.uuid4(),
        )
        return True

    def apply(
        self,
        target: PaintTargetContext,
        segment: BrushStrokeSegment,
        preset: BrushPreset,
        color: QColor,
    ) -> bool:
        """Composite one shared segment into live selection coverage."""
        session = self._matching_session(target)
        if session is None:
            return False
        configured = self._compiler.compile(segment, preset)
        session.segments = (*session.segments, configured)
        item = StrokeCoverageItem(
            session.item_id,
            session.segments,
            (
                CoverageCombineMode.SUBTRACT
                if configured.operation is BrushOperation.ERASE
                else CoverageCombineMode.ADD
            ),
        )
        base = CoverageDocument() if session.before is None else session.before
        return self._selections.preview_document(
            target.scene.scene_id,
            base.add(item),
        )

    def commit(self, target: PaintTargetContext) -> bool:
        """Record one already-presented selection stroke in chronology."""
        session = self._matching_session(target)
        self._session = None
        return (
            False
            if session is None
            else self._selections.record_preview(
                target.scene.scene_id,
                session.before,
            )
        )

    def cancel(self, target: PaintTargetContext) -> bool:
        """Restore the selection captured before the unresolved stroke."""
        session = self._matching_session(target)
        self._session = None
        return (
            False
            if session is None
            else self._selections.restore_document(
                target.scene.scene_id,
                session.before,
            )
        )

    def preview_color(self, target: PaintTargetContext, fallback: QColor) -> QColor:
        """Return a stable selection-blue brush feedback color."""
        return QColor(75, 145, 255, 255)

    def commit_coverage_item(
        self,
        target: PaintTargetContext,
        item: CoverageItem,
    ) -> bool:
        """Commit retained geometry into the target composition selection."""
        return self._selections.commit_item(target.scene.scene_id, item)

    def _matching_session(
        self,
        target: PaintTargetContext,
    ) -> _SelectionPaintSession | None:
        """Return the active session only for its exact composition."""
        session = self._session
        return (
            session
            if session is not None and session.scene_id == target.scene.scene_id
            else None
        )
