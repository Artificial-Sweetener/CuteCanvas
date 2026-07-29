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
"""Focused public Clone Stamp configuration and activation facade."""

from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import QPointF

from ..painting.clone_model import (
    CloneStampAlignment,
    CloneStampSampleMode,
    CloneStampState,
    CloneStampTransform,
)
from ..types import ControlMode


class CloneStampHost(Protocol):
    """Describe widget commands delegated by the Clone Stamp facade."""

    def setControlMode(self, mode: str) -> bool:
        """Activate one registered tool mode."""
        ...

    def cloneStampState(self) -> CloneStampState:
        """Return current Clone Stamp configuration."""
        ...

    def setCloneStampSource(self, scene_position: QPointF) -> bool:
        """Set a source in active-document scene coordinates."""
        ...

    def clearCloneStampSource(self) -> bool:
        """Clear the current source."""
        ...

    def setCloneStampAlignment(self, alignment: CloneStampAlignment) -> bool:
        """Replace alignment behavior."""
        ...

    def setCloneStampSampleMode(self, mode: CloneStampSampleMode) -> bool:
        """Replace source sampling behavior."""
        ...

    def setCloneStampTransform(self, transform: CloneStampTransform) -> bool:
        """Replace sampled-content transform behavior."""
        ...


class CloneStampFacade:
    """Expose Clone Stamp state and commands without duplicating document state."""

    def __init__(self, host: CloneStampHost) -> None:
        """Bind the authoritative widget command boundary."""
        self._host = host

    @property
    def state(self) -> CloneStampState:
        """Return current immutable source and configuration state."""
        return self._host.cloneStampState()

    def activate(self) -> bool:
        """Select the Clone Stamp tool and report acceptance."""
        return self._host.setControlMode(ControlMode.CLONE_STAMP.value)

    def set_source(self, scene_position: QPointF) -> bool:
        """Set a source in active-document scene coordinates."""
        return self._host.setCloneStampSource(scene_position)

    def clear_source(self) -> bool:
        """Clear the source and retained aligned offset."""
        return self._host.clearCloneStampSource()

    def set_alignment(self, alignment: CloneStampAlignment) -> bool:
        """Set whether source offset persists between separate strokes."""
        return self._host.setCloneStampAlignment(alignment)

    def set_sample_mode(self, mode: CloneStampSampleMode) -> bool:
        """Choose the anchored layer range or visible composition source."""
        return self._host.setCloneStampSampleMode(mode)

    def set_transform(self, transform: CloneStampTransform) -> bool:
        """Set rotation, output scale, and reflection for sampled content."""
        return self._host.setCloneStampTransform(transform)
