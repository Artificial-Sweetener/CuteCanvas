#    QPane - High-performance PySide6 image viewer
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

"""Brush contact-session ownership independent of Qt event delivery."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF

from ..stroke_models import MaskStrokeSegmentPayload


@dataclass(frozen=True, slots=True)
class BrushContact:
    """Capture one image-space brush contact sample."""

    position: QPointF
    diameter: float
    erase: bool


class BrushStrokeSession:
    """Own one captured pointer and convert its samples into stroke segments."""

    def __init__(self) -> None:
        """Initialize an idle session."""
        self._pointer_id: int | None = None
        self._previous: BrushContact | None = None

    @property
    def active(self) -> bool:
        """Return whether a pointer currently owns the stroke."""
        return self._pointer_id is not None

    @property
    def pointer_id(self) -> int | None:
        """Return the captured pointer identifier."""
        return self._pointer_id

    def begin(
        self,
        pointer_id: int,
        position: QPointF,
        diameter: float,
        erase: bool,
    ) -> MaskStrokeSegmentPayload:
        """Capture ``pointer_id`` and return its initial dab."""
        contact = self._contact(position, diameter, erase)
        self._pointer_id = int(pointer_id)
        self._previous = contact
        return self._segment(contact, contact)

    def update(
        self,
        pointer_id: int,
        position: QPointF,
        diameter: float,
        erase: bool,
    ) -> MaskStrokeSegmentPayload | None:
        """Return the next segment when ``pointer_id`` owns this session."""
        if self._pointer_id != int(pointer_id) or self._previous is None:
            return None
        current = self._contact(position, diameter, erase)
        previous = self._previous
        self._previous = current
        if (
            current.position == previous.position
            and current.diameter == previous.diameter
        ):
            return None
        return self._segment(previous, current)

    def end(
        self,
        pointer_id: int,
        position: QPointF,
        diameter: float,
        erase: bool,
    ) -> MaskStrokeSegmentPayload | None:
        """Apply a final sample and release the captured pointer."""
        segment = self.update(pointer_id, position, diameter, erase)
        if self._pointer_id == int(pointer_id):
            self.cancel()
        return segment

    def cancel(self) -> None:
        """Release pointer capture and discard transient sample state."""
        self._pointer_id = None
        self._previous = None

    @staticmethod
    def _contact(position: QPointF, diameter: float, erase: bool) -> BrushContact:
        """Normalize one contact before storing it."""
        return BrushContact(
            position=QPointF(position),
            diameter=max(1.0, float(diameter)),
            erase=bool(erase),
        )

    @staticmethod
    def _segment(
        start: BrushContact,
        end: BrushContact,
    ) -> MaskStrokeSegmentPayload:
        """Build an immutable segment between two contacts."""
        return MaskStrokeSegmentPayload(
            start=(start.position.x(), start.position.y()),
            end=(end.position.x(), end.position.y()),
            start_diameter=start.diameter,
            end_diameter=end.diameter,
            erase=end.erase,
        )
