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

"""Strict configuration validation covering enums and diagnostics domains."""

from __future__ import annotations

import pytest
from cutecanvas import Config, CuteCanvas
from qpane.core.config import CacheSettings, PlaceholderSettings
from qpane.types import (
    CacheMode,
    DiagnosticsDomain,
    PlaceholderScaleMode,
    ZoomMode,
)


def test_config_rejects_unknown_top_level_keys() -> None:
    """Raise when callers provide unsupported configuration keys."""
    config = Config()
    with pytest.raises(ValueError):
        config.configure(unknown_toggle=True)


def test_cache_settings_normalize_enum_and_reject_unknown() -> None:
    """CacheSettings accepts enums and rejects unsupported values and keys."""
    settings = CacheSettings()
    settings.apply_mapping({"mode": CacheMode.HARD})
    assert settings.mode == "hard"
    with pytest.raises(ValueError):
        settings.apply_mapping({"mode": "dynamic"})
    with pytest.raises(ValueError):
        settings.apply_mapping({"unsupported_bucket": 5})


def test_placeholder_settings_normalize_enums_and_sizes() -> None:
    """PlaceholderSettings accepts enums and validates size inputs."""
    settings = PlaceholderSettings()
    settings.apply_mapping(
        {
            "panzoom_enabled": True,
            "zoom_mode": ZoomMode.FIT,
            "scale_mode": PlaceholderScaleMode.LOGICAL_FIT,
            "locked_size": (100, 200),
        }
    )
    assert settings.panzoom_enabled is True
    assert settings.zoom_mode == "fit"
    assert settings.scale_mode == "logical_fit"
    assert settings.locked_size == (100, 200)
    with pytest.raises(TypeError):
        settings.apply_mapping({"locked_size": "bad"})  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        settings.apply_mapping({"locked_size": (0, 10)})
    with pytest.raises(ValueError):
        settings.apply_mapping({"unsupported": True})


def test_diagnostics_domains_normalize_and_allow_extensions() -> None:
    """Diagnostics configuration should accept renderer and extension domains."""
    config = Config()
    config.configure(
        diagnostics_domains_enabled=(DiagnosticsDomain.CACHE, "swap"),
    )
    assert config.diagnostics_domains_enabled == ("cache", "swap")
    config.configure(diagnostics_domains_enabled=("custom-domain",))
    assert config.diagnostics_domains_enabled == ("custom-domain",)
    with pytest.raises(ValueError):
        config.configure(diagnostics_domains_enabled=(" ",))


def test_qpane_rejects_unknown_diagnostics_domain(qapp) -> None:
    """CuteCanvas raises when toggling diagnostics domains that are unavailable."""
    qpane = CuteCanvas(features=())
    try:
        available = set(qpane.diagnosticsDomains())
        unknown = "custom.missing"
        if unknown in available:
            unknown = "diagnostics-missing"
        with pytest.raises(ValueError):
            qpane.setDiagnosticsDomainEnabled(unknown, True)
    finally:
        qpane.deleteLater()
        qapp.processEvents()
