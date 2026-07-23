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
"""Mounted live diagnostics contracts for the standalone QPane viewer."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QColor, QImage
from qpane import DiagnosticRecord, QPane

from tests.harness.timing import interaction_clock


def _mounted_viewer(qapp) -> QPane:
    """Return a rendered viewer with active tile and pyramid collaborators."""
    pane = QPane()
    pane.resize(800, 600)
    image = QImage(1400, 900, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("royalblue"))
    pane.addImage(image, label="Diagnostic fixture")
    pane.show()
    qapp.processEvents()
    return pane


def test_live_diagnostics_report_real_renderer_owners(qapp) -> None:
    """Core and enabled detail rows come from live rendering collaborators."""
    pane = _mounted_viewer(qapp)
    pane.setDiagnosticsDomainEnabled("cache", True)
    pane.setDiagnosticsDomainEnabled("executor", True)
    pane.setDiagnosticsDomainEnabled("swap", True)

    rows = dict(pane.gatherDiagnostics().rows())

    assert {"Paint", "Zoom", "Cache", "Cache|Tiles", "Cache|Pyramids"} <= rows.keys()
    assert "Executor" in rows
    assert "Catalog Prefetch" in rows
    pane.close()
    pane.deleteLater()


def test_diagnostics_overlay_and_custom_provider_follow_public_lifecycle(qapp) -> None:
    """The public HUD and host provider update without demo-owned substitutes."""
    pane = _mounted_viewer(qapp)
    toggles: list[bool] = []
    pane.diagnosticsOverlayToggled.connect(toggles.append)
    pane.registerDiagnosticsProvider(
        lambda _pane: (DiagnosticRecord("Host", "ready"),),
        domain="host",
    )

    pane.setDiagnosticsOverlayEnabled(True)
    qapp.processEvents()
    assert pane.diagnosticsOverlayEnabled()
    assert toggles == [True]
    assert ("Host", "ready") in pane.gatherDiagnostics().rows()

    pane.setDiagnosticsOverlayEnabled(False)
    assert not pane.diagnosticsOverlayEnabled()
    assert toggles[-1] is False
    pane.close()
    pane.deleteLater()


def test_diagnostics_preferences_are_atomic_and_storm_responsive(qapp) -> None:
    """Invalid domains cannot partially mutate config and rapid toggles stay cheap."""
    pane = _mounted_viewer(qapp)
    previous = pane.settings.copy()
    with pytest.raises(ValueError, match="Unknown diagnostics domains"):
        pane.applySettings(
            diagnostics_overlay_enabled=True,
            diagnostics_domains_enabled=("cache", "not-a-domain"),
        )
    assert pane.settings.as_dict() == previous.as_dict()
    assert not pane.diagnosticsOverlayEnabled()

    domains = pane.diagnosticsDomains()
    started = interaction_clock()
    for index in range(600):
        domain = domains[index % len(domains)]
        pane.setDiagnosticsDomainEnabled(domain, index % 2 == 0)
        pane.gatherDiagnostics()
    elapsed_ms = (interaction_clock() - started) * 1000.0

    assert elapsed_ms < 750.0
    pane.close()
    pane.deleteLater()
    qapp.processEvents()
