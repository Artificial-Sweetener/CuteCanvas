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

import sys
import types

from cutecanvas.core import FeatureCoordinator, FeatureFallbacks
from cutecanvas.core.feature_coordinator import _FeatureSpec


class DummyQPane:
    """Minimal CuteCanvas stub used for coordinator tests."""


def test_unknown_feature_records_failure_and_fallback(monkeypatch):
    monkeypatch.setattr(
        "cutecanvas.core.feature_coordinator._DEFAULT_FEATURE_SPECS", ()
    )
    fallbacks = FeatureFallbacks()
    coordinator = FeatureCoordinator(DummyQPane(), fallbacks)
    summary = coordinator.install(("mystery",))
    assert summary.installed == ()
    assert "mystery" in summary.failed
    failure = summary.failed["mystery"]
    assert failure.message == "Requested feature is not registered."
    assert failure.hint is None
    assert fallbacks.get_reason("mystery") == "Requested feature is not registered."


def test_import_failure_surfaces_hint_and_cause(monkeypatch):
    spec = _FeatureSpec(
        name="ghost",
        module_path="tests.missing_feature_module",
        installer_name="install",
        missing_module_message="Missing ghost feature module.",
        hint="Install the ghost extras via 'pip install qpane[ghost]'.",
    )
    monkeypatch.setattr(
        "cutecanvas.core.feature_coordinator._DEFAULT_FEATURE_SPECS", (spec,)
    )
    fallbacks = FeatureFallbacks()
    coordinator = FeatureCoordinator(DummyQPane(), fallbacks)
    summary = coordinator.install(("ghost",))
    assert summary.installed == ()
    failure = summary.failed["ghost"]
    assert failure.message == "Missing ghost feature module."
    assert failure.hint == "Install the ghost extras via 'pip install qpane[ghost]'."
    assert isinstance(failure.cause, ImportError)
    assert fallbacks.get_failure("ghost") is failure
    assert summary.failure_messages()["ghost"].startswith(
        "Missing ghost feature module."
    )


def test_successful_install_records_success(monkeypatch):
    module_name = "tests.fake_feature_module"
    module = types.ModuleType(module_name)

    def install_fake_feature(qpane):
        qpane.installed_flag = True

    module.install_fake_feature = install_fake_feature
    monkeypatch.setitem(sys.modules, module_name, module)
    spec = _FeatureSpec(
        name="fake",
        module_path=module_name,
        installer_name="install_fake_feature",
    )
    monkeypatch.setattr(
        "cutecanvas.core.feature_coordinator._DEFAULT_FEATURE_SPECS", (spec,)
    )
    fallbacks = FeatureFallbacks()
    qpane = DummyQPane()
    coordinator = FeatureCoordinator(qpane, fallbacks)
    summary = coordinator.install(("fake",))
    assert summary.installed == ("fake",)
    assert not summary.failed
    assert getattr(qpane, "installed_flag", False) is True
    assert fallbacks.is_available("fake")
