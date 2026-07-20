#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Source-neutral brush contact session independent of Qt event delivery."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF

from .model import BrushOperation, BrushStrokeSegment


@dataclass(frozen=True, slots=True)
class BrushContact:
    """Capture one target-local brush contact sample."""

    position: QPointF
    diameter: float
    operation: BrushOperation
    pressure: float
    tilt_x: float = 0.0
    tilt_y: float = 0.0
    rotation: float = 0.0
    tangential_pressure: float = 0.0


class BrushStrokeSession:
    """Own captured contact state and produce source-neutral segments."""

    def __init__(self) -> None:
        """Initialize an idle deterministic sequence."""
        self._pointer_id: int | None = None
        self._previous: BrushContact | None = None
        self._sequence = 0

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
        *,
        pressure: float = 1.0,
        tilt_x: float = 0.0,
        tilt_y: float = 0.0,
        rotation: float = 0.0,
        tangential_pressure: float = 0.0,
    ) -> BrushStrokeSegment:
        """Capture ``pointer_id`` and return its initial dab segment."""
        contact = self._contact(
            position,
            diameter,
            erase,
            pressure,
            tilt_x,
            tilt_y,
            rotation,
            tangential_pressure,
        )
        self._pointer_id = int(pointer_id)
        self._previous = contact
        self._sequence = 0
        return self._segment(contact, contact)

    def update(
        self,
        pointer_id: int,
        position: QPointF,
        diameter: float,
        erase: bool,
        *,
        pressure: float = 1.0,
        tilt_x: float = 0.0,
        tilt_y: float = 0.0,
        rotation: float = 0.0,
        tangential_pressure: float = 0.0,
        smoothing: float = 0.0,
    ) -> BrushStrokeSegment | None:
        """Return the next segment when ``pointer_id`` owns this session."""
        if self._pointer_id != int(pointer_id) or self._previous is None:
            return None
        retention = min(0.95, max(0.0, float(smoothing)) * 0.95)
        smoothed_position = QPointF(
            self._previous.position.x() * retention + position.x() * (1.0 - retention),
            self._previous.position.y() * retention + position.y() * (1.0 - retention),
        )
        current = self._contact(
            smoothed_position,
            diameter,
            erase,
            pressure,
            tilt_x,
            tilt_y,
            rotation,
            tangential_pressure,
        )
        previous = self._previous
        self._previous = current
        if (
            current.position == previous.position
            and current.diameter == previous.diameter
        ):
            return None
        self._sequence += 1
        return self._segment(previous, current)

    def end(
        self,
        pointer_id: int,
        position: QPointF,
        diameter: float,
        erase: bool,
        *,
        pressure: float = 1.0,
        tilt_x: float = 0.0,
        tilt_y: float = 0.0,
        rotation: float = 0.0,
        tangential_pressure: float = 0.0,
        smoothing: float = 0.0,
    ) -> BrushStrokeSegment | None:
        """Apply a final sample and release the captured pointer."""
        segment = self.update(
            pointer_id,
            position,
            diameter,
            erase,
            pressure=pressure,
            tilt_x=tilt_x,
            tilt_y=tilt_y,
            rotation=rotation,
            tangential_pressure=tangential_pressure,
            smoothing=smoothing,
        )
        if self._pointer_id == int(pointer_id):
            self.cancel()
        return segment

    def cancel(self) -> None:
        """Release pointer capture and discard transient sample state."""
        self._pointer_id = None
        self._previous = None
        self._sequence = 0

    @staticmethod
    def _contact(
        position: QPointF,
        diameter: float,
        erase: bool,
        pressure: float,
        tilt_x: float,
        tilt_y: float,
        rotation: float,
        tangential_pressure: float,
    ) -> BrushContact:
        """Normalize one contact before storing it."""
        return BrushContact(
            position=QPointF(position),
            diameter=max(1.0, float(diameter)),
            operation=BrushOperation.ERASE if erase else BrushOperation.PAINT,
            pressure=min(1.0, max(0.0, float(pressure))),
            tilt_x=float(tilt_x),
            tilt_y=float(tilt_y),
            rotation=float(rotation),
            tangential_pressure=min(
                1.0,
                max(-1.0, float(tangential_pressure)),
            ),
        )

    def _segment(self, start: BrushContact, end: BrushContact) -> BrushStrokeSegment:
        """Build an immutable segment between two contacts."""
        return BrushStrokeSegment(
            start=(start.position.x(), start.position.y()),
            end=(end.position.x(), end.position.y()),
            start_diameter=start.diameter,
            end_diameter=end.diameter,
            operation=end.operation,
            sequence=self._sequence,
            continuation=self._sequence > 0,
            start_pressure=start.pressure,
            end_pressure=end.pressure,
            start_tilt_x=start.tilt_x,
            start_tilt_y=start.tilt_y,
            end_tilt_x=end.tilt_x,
            end_tilt_y=end.tilt_y,
            start_rotation=start.rotation,
            end_rotation=end.rotation,
            start_tangential_pressure=start.tangential_pressure,
            end_tangential_pressure=end.tangential_pressure,
            size_dynamics_applied=True,
        )
