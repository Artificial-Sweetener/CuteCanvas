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

"""Controller that manages QPane diagnostics overlays and detail toggles."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from .status_overlay import QPaneStatusOverlay

if TYPE_CHECKING:  # pragma: no cover - import guard for typing only
    from ..viewer import QPane


class DiagnosticsOverlayController:
    """Own the diagnostics overlay widget and domain detail toggles."""

    def __init__(self, qpane: QPane) -> None:
        """Cache QPane reference and initialize overlay/detail state trackers."""
        self._qpane = qpane
        self._overlay: QPaneStatusOverlay | None = None
        self._enabled = False
        self._detail_states: dict[str, bool] = {}
        self._on_overlay_changed: Callable[[bool], None] | None = None
        self._on_detail_changed: Callable[[str, bool], None] | None = None

    def overlayEnabled(self) -> bool:
        """Return True when the overlay widget is currently active."""
        return self._enabled

    def setOverlayEnabled(self, enabled: bool) -> None:
        """Toggle the overlay widget and start/stop refresh timers."""
        if self._enabled == enabled:
            return
        self._enabled = enabled
        if enabled:
            overlay = self._ensure_overlay()
        else:
            overlay = self._overlay
            if overlay is None:
                return
        overlay.set_active(enabled)
        if self._on_overlay_changed is not None:
            self._on_overlay_changed(enabled)

    def domains(self) -> tuple[str, ...]:
        """Return domain names that expose detail-tier diagnostics providers."""
        return self._qpane.diagnostics().detail_domains()

    def domainEnabled(self, domain: str) -> bool:
        """Return True when detail-tier providers for ``domain`` are active."""
        return self._detail_states.get(domain, False)

    def setDomainEnabled(self, domain: str, enabled: bool) -> None:
        """Enable or disable detail-tier providers for ``domain``."""
        current = self._detail_states.get(domain)
        if current == enabled:
            return
        self._detail_states[domain] = enabled
        diagnostics = self._qpane.diagnostics()
        diagnostics.set_domain_detail_enabled(domain, enabled)
        if self._enabled and self._overlay is not None:
            self._overlay.refresh()
        if self._on_detail_changed is not None:
            self._on_detail_changed(domain, enabled)

    def setOverlayChangedCallback(
        self, callback: Callable[[bool], None] | None
    ) -> None:
        """Register a callback invoked when overlay visibility changes."""
        self._on_overlay_changed = callback

    def setDetailChangedCallback(
        self, callback: Callable[[str, bool], None] | None
    ) -> None:
        """Register a callback invoked when detail toggles change."""
        self._on_detail_changed = callback

    def _ensure_overlay(self) -> QPaneStatusOverlay:
        """Create the overlay widget if it has not been instantiated."""
        if self._overlay is None:
            self._overlay = self._qpane.createStatusOverlay()
        return self._overlay
