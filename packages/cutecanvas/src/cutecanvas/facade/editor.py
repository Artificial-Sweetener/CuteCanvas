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
"""Focused public editor subfacades with no duplicate durable state."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from PySide6.QtCore import QPointF, QRect, QRectF
from PySide6.QtGui import QImage
from qpane.sdk.vector import VectorShapeKind

from ..types import CoverageCoordinateSpace, PixelSelectionMode, PixelSelectionSnapshot
from .clone_stamp import CloneStampFacade, CloneStampHost
from .effects import EffectsFacade
from .handles import CompositionCollection, EditorHandleHost
from .persistence import CompositionPersistenceFacade

if TYPE_CHECKING:
    from ..persistence import CompositionPersistenceService


class EditorCommandHost(EditorHandleHost, CloneStampHost, Protocol):
    """Describe focused tool, selection, and history commands."""

    def availableControlModes(self) -> tuple[str, ...]:
        """Return registered tool modes."""
        ...

    def getControlMode(self) -> str:
        """Return the active tool mode."""
        ...

    def setControlMode(self, mode: str) -> None:
        """Activate one registered tool mode."""
        ...

    def pixelSelectionState(self) -> PixelSelectionSnapshot | None:
        """Return active pixel-selection state."""
        ...

    def clearPixelSelection(self) -> bool:
        """Deselect pixels, resolving any floating edit first."""
        ...

    def sceneEditUndoAvailable(self) -> bool:
        """Return whether undo is available in the active document."""
        ...

    def sceneEditRedoAvailable(self) -> bool:
        """Return whether redo is available in the active document."""
        ...

    def undoSceneEdit(self) -> bool:
        """Undo one active-document edit."""
        ...

    def redoSceneEdit(self) -> bool:
        """Redo one active-document edit."""
        ...

    def addCoverageShape(
        self,
        shape: VectorShapeKind,
        bounds: QRectF,
        mode: PixelSelectionMode = PixelSelectionMode.ADD,
        *,
        feather_radius: float | None = None,
        coordinate_space: CoverageCoordinateSpace = CoverageCoordinateSpace.TARGET,
    ) -> uuid.UUID | None:
        """Add retained shape geometry to the active coverage target."""
        ...

    def addCoveragePolygon(
        self,
        points: Iterable[QPointF],
        mode: PixelSelectionMode = PixelSelectionMode.ADD,
        *,
        feather_radius: float | None = None,
        coordinate_space: CoverageCoordinateSpace = CoverageCoordinateSpace.TARGET,
    ) -> uuid.UUID | None:
        """Add retained polygon geometry to the active coverage target."""
        ...

    def addCoverageImage(
        self,
        coverage: QImage,
        bounds: QRect,
        mode: PixelSelectionMode = PixelSelectionMode.ADD,
    ) -> uuid.UUID | None:
        """Add arbitrary pixels to the active coverage target."""
        ...


class ToolFacade:
    """Expose tool activation independently of document state."""

    def __init__(self, host: EditorCommandHost) -> None:
        """Bind the authoritative widget tool boundary."""
        self._host = host

    @property
    def available(self) -> tuple[str, ...]:
        """Return every registered public tool mode."""
        return self._host.availableControlModes()

    @property
    def active(self) -> str:
        """Return the active tool mode."""
        return self._host.getControlMode()

    def activate(self, mode: str) -> None:
        """Activate one registered tool mode."""
        self._host.setControlMode(mode)


class HistoryFacade:
    """Expose the active document's one chronological edit history."""

    def __init__(self, host: EditorCommandHost) -> None:
        """Bind the authoritative composition history boundary."""
        self._host = host

    @property
    def can_undo(self) -> bool:
        """Return whether one edit can be undone now."""
        return self._host.sceneEditUndoAvailable()

    @property
    def can_redo(self) -> bool:
        """Return whether one edit can be redone now."""
        return self._host.sceneEditRedoAvailable()

    def undo(self) -> bool:
        """Undo one chronological edit in the active document."""
        return self._host.undoSceneEdit()

    def redo(self) -> bool:
        """Redo one chronological edit in the active document."""
        return self._host.redoSceneEdit()


class SelectionFacade:
    """Expose active-document pixel selection without owning coverage."""

    def __init__(self, host: EditorCommandHost) -> None:
        """Bind the authoritative pixel-selection boundary."""
        self._host = host

    @property
    def state(self) -> PixelSelectionSnapshot | None:
        """Return a detached snapshot of the active pixel selection."""
        return self._host.pixelSelectionState()

    def clear(self) -> bool:
        """Deselect pixels after resolving any unresolved floating edit."""
        return self._host.clearPixelSelection()


class CoverageFacade:
    """Author retained shapes and pixels through the active coverage target."""

    def __init__(self, host: EditorCommandHost) -> None:
        """Bind the authoritative widget coverage boundary."""
        self._host = host

    def rectangle(
        self,
        bounds: QRectF,
        mode: PixelSelectionMode = PixelSelectionMode.ADD,
        *,
        feather_radius: float | None = None,
        coordinate_space: CoverageCoordinateSpace = CoverageCoordinateSpace.TARGET,
    ) -> uuid.UUID | None:
        """Add one retained rectangle in active-target coordinates."""
        return self._host.addCoverageShape(
            VectorShapeKind.RECTANGLE,
            bounds,
            mode,
            feather_radius=feather_radius,
            coordinate_space=coordinate_space,
        )

    def ellipse(
        self,
        bounds: QRectF,
        mode: PixelSelectionMode = PixelSelectionMode.ADD,
        *,
        feather_radius: float | None = None,
        coordinate_space: CoverageCoordinateSpace = CoverageCoordinateSpace.TARGET,
    ) -> uuid.UUID | None:
        """Add one retained ellipse in active-target coordinates."""
        return self._host.addCoverageShape(
            VectorShapeKind.ELLIPSE,
            bounds,
            mode,
            feather_radius=feather_radius,
            coordinate_space=coordinate_space,
        )

    def polygon(
        self,
        points: Iterable[QPointF],
        mode: PixelSelectionMode = PixelSelectionMode.ADD,
        *,
        feather_radius: float | None = None,
        coordinate_space: CoverageCoordinateSpace = CoverageCoordinateSpace.TARGET,
    ) -> uuid.UUID | None:
        """Add one retained closed polygon in active-target coordinates."""
        return self._host.addCoveragePolygon(
            points,
            mode,
            feather_radius=feather_radius,
            coordinate_space=coordinate_space,
        )

    def image(
        self,
        coverage: QImage,
        bounds: QRect,
        mode: PixelSelectionMode = PixelSelectionMode.ADD,
    ) -> uuid.UUID | None:
        """Add arbitrary soft coverage in active-target coordinates."""
        return self._host.addCoverageImage(coverage, bounds, mode)


@dataclass(frozen=True, slots=True)
class EditorFacade:
    """Collect focused public editor APIs around one CuteCanvas widget."""

    compositions: CompositionCollection
    tools: ToolFacade
    clone_stamp: CloneStampFacade
    selection: SelectionFacade
    coverage: CoverageFacade
    effects: EffectsFacade
    history: HistoryFacade
    persistence: CompositionPersistenceFacade

    @classmethod
    def create(
        cls,
        host: EditorCommandHost,
        persistence: CompositionPersistenceService,
    ) -> EditorFacade:
        """Build focused APIs that all delegate to existing state owners."""
        return cls(
            CompositionCollection(host),
            ToolFacade(host),
            CloneStampFacade(host),
            SelectionFacade(host),
            CoverageFacade(host),
            EffectsFacade(host),
            HistoryFacade(host),
            CompositionPersistenceFacade(host, persistence),
        )
