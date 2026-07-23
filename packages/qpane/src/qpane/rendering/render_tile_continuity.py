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
"""Presentation stability policy for sampled rendering during viewport motion."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer

from .render_tile_geometry import RenderTileKey

_SETTLE_INTERVAL_MS = 50
_SourceIdentity = tuple[str, uuid.UUID]


@dataclass(slots=True)
class _ContinuityState:
    """Track one source's latest view and temporary fallback preference."""

    visible_signature: tuple[RenderTileKey, ...]
    fallback_active: bool = False
    exact_available: bool = False


class RenderTileContinuity(QObject):
    """Prevent exact and fallback resolutions from alternating during motion."""

    def __init__(self, ready: Callable[[], None]) -> None:
        """Create one global viewport-settle boundary for sampled sources."""
        super().__init__()
        self._ready = ready
        self._states: dict[_SourceIdentity, _ContinuityState] = {}
        self._closed = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_SETTLE_INTERVAL_MS)
        self._timer.timeout.connect(self._handle_settled)

    @property
    def pending(self) -> bool:
        """Return whether presentation still awaits a stable exact frame."""
        return any(state.fallback_active for state in self._states.values())

    def prefer_fallback(
        self,
        identity: _SourceIdentity,
        visible_signature: tuple[RenderTileKey, ...],
        *,
        exact_available: bool,
    ) -> bool:
        """Return whether stable fallback density should remain presented."""
        if self._closed:
            return False
        state = self._states.get(identity)
        if state is None:
            state = _ContinuityState(visible_signature)
            self._states[identity] = state
            self._timer.start()
        elif state.visible_signature != visible_signature:
            state.visible_signature = visible_signature
            self._timer.start()
        state.exact_available = exact_available
        if not exact_available:
            state.fallback_active = True
        elif state.fallback_active and not self._timer.isActive():
            state.fallback_active = False
        return state.fallback_active

    def visible_signature(
        self,
        identity: _SourceIdentity,
    ) -> tuple[RenderTileKey, ...] | None:
        """Return the latest visible signature tracked for one source."""
        state = self._states.get(identity)
        return None if state is None else state.visible_signature

    def note_exact_available(
        self,
        identity: _SourceIdentity,
        *,
        exact_available: bool,
    ) -> None:
        """Record cache publication and settle from its actual arrival time."""
        state = self._states.get(identity)
        if state is None:
            return
        became_available = exact_available and not state.exact_available
        state.exact_available = exact_available
        if became_available and state.fallback_active:
            self._timer.start()

    def shutdown(self) -> None:
        """Stop settle publication and release source state."""
        if self._closed:
            return
        self._closed = True
        try:
            self._timer.stop()
        except RuntimeError:
            pass
        self._states.clear()

    def _handle_settled(self) -> None:
        """Request one frame that may promote settled exact products."""
        promotable = any(
            state.fallback_active and state.exact_available
            for state in self._states.values()
        )
        if not self._closed and promotable:
            try:
                self._ready()
            except RuntimeError:
                self.shutdown()
