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
"""Subscription-based change publication for a headless canvas document."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum


class DocumentChangeKind(str, Enum):
    """Name a durable document-domain change."""

    HISTORY = "history"
    LAYERS = "layers"
    RESOURCE = "resource"
    SELECTION = "selection"


@dataclass(frozen=True, slots=True)
class DocumentChange:
    """Describe one durable change without retaining widget state."""

    kind: DocumentChangeKind
    composition_id: uuid.UUID | None = None
    resource_id: uuid.UUID | None = None
    payload: object | None = None


@dataclass(slots=True)
class DocumentEventHub:
    """Publish durable changes to any number of independently mounted views."""

    _subscribers: list[Callable[[DocumentChange], None]] = field(default_factory=list)

    def subscribe(
        self,
        callback: Callable[[DocumentChange], None],
    ) -> Callable[[], None]:
        """Register a subscriber and return an idempotent detach function."""
        if callback not in self._subscribers:
            self._subscribers.append(callback)

        def unsubscribe() -> None:
            """Detach the subscriber once when the returned callback is invoked."""
            if callback in self._subscribers:
                self._subscribers.remove(callback)

        return unsubscribe

    def publish(self, change: DocumentChange) -> None:
        """Publish one immutable change to a stable subscriber snapshot."""
        for callback in tuple(self._subscribers):
            callback(change)

    def clear(self) -> None:
        """Detach every subscriber when its document owner closes."""
        self._subscribers.clear()

    def history_changed(self, composition_id: uuid.UUID) -> None:
        """Publish one chronological-history mutation."""
        self.publish(DocumentChange(DocumentChangeKind.HISTORY, composition_id))

    def layers_changed(self, composition_id: uuid.UUID) -> None:
        """Publish one composition layer-stack mutation."""
        self.publish(DocumentChange(DocumentChangeKind.LAYERS, composition_id))

    def resource_changed(
        self,
        resource_id: uuid.UUID,
        dirty_region: object | None = None,
    ) -> None:
        """Publish one resource-content mutation and its optional local region."""
        self.publish(
            DocumentChange(
                DocumentChangeKind.RESOURCE,
                resource_id=resource_id,
                payload=dirty_region,
            )
        )

    def selection_changed(self, state: object) -> None:
        """Publish one composition-owned pixel-selection mutation."""
        composition_id = getattr(state, "scene_id", None)
        self.publish(
            DocumentChange(
                DocumentChangeKind.SELECTION,
                composition_id=(
                    composition_id if isinstance(composition_id, uuid.UUID) else None
                ),
                payload=state,
            )
        )
