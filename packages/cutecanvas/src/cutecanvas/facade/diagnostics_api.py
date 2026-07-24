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
"""Diagnostics overlay methods for the CuteCanvas facade."""

from __future__ import annotations

from cutecanvas.types import DiagnosticsDomain


class DiagnosticsApiMixin:
    """Expose diagnostics visibility without owning diagnostic providers."""

    def diagnosticsOverlayEnabled(self) -> bool:
        """Return whether the diagnostics overlay is visible."""
        return self.diagnosticsOverlayController().overlayEnabled()

    def diagnosticsDomains(self) -> tuple[str, ...]:
        """Return diagnostics domains with detail providers."""
        return self.diagnosticsOverlayController().domains()

    def diagnosticsDomainEnabled(self, domain: str | DiagnosticsDomain) -> bool:
        """Return whether one diagnostics detail domain is enabled."""
        canonical = self._normalize_diagnostics_domain(domain)
        return self.diagnosticsOverlayController().domainEnabled(canonical)

    def setDiagnosticsOverlayEnabled(self, enabled: bool) -> None:
        """Show or hide the diagnostics overlay."""
        self.diagnosticsOverlayController().setOverlayEnabled(enabled)

    def setDiagnosticsDomainEnabled(
        self,
        domain: str | DiagnosticsDomain,
        enabled: bool,
    ) -> None:
        """Enable or disable one diagnostics detail domain."""
        canonical = self._normalize_diagnostics_domain(domain)
        self.diagnosticsOverlayController().setDomainEnabled(canonical, enabled)
