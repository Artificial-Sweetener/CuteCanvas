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

"""Independent Qt fixtures for CuteCanvas's package test suite."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from cutecanvas import CuteCanvas
from cutecanvas.core import config
from cutecanvas_test_support.harness.process_lock import (
    interactive_performance_isolation,
)
from cutecanvas_test_support.harness.qt_lifetime import flush_deferred_qt_lifetime
from cutecanvas_test_support.mask_workflow import provision_canvas_with_mask
from PySide6.QtWidgets import QApplication
from qpane import QPane


@pytest.fixture(autouse=True)
def _isolate_interactive_performance(
    request: pytest.FixtureRequest,
) -> Iterator[None]:
    """Participate in suite-wide strict performance isolation."""
    with interactive_performance_isolation(request):
        yield


@pytest.fixture(scope="session")
def qapp() -> Iterator[QApplication]:
    """Provide one offscreen application for mounted editor tests."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _flush_deferred_qt_deletions(qapp: QApplication) -> Iterator[None]:
    """Deliver deferred Qt deletions after each package test."""
    yield
    flush_deferred_qt_lifetime(qapp)


@pytest.fixture
def canvas_core(qapp: QApplication) -> Iterator[CuteCanvas]:
    """Provide a bare CuteCanvas editor and dispose it after the test."""
    del qapp
    canvas = CuteCanvas(features=())
    try:
        yield canvas
    finally:
        canvas.deleteLater()


@pytest.fixture
def qpane_core(qapp: QApplication) -> Iterator[QPane]:
    """Provide QPane's public facade for downstream input-contract tests."""
    del qapp
    pane = QPane()
    try:
        yield pane
    finally:
        pane.deleteLater()


@pytest.fixture
def qpane_with_mask(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[CuteCanvas, object, object]]:
    """Provide the package-owned deterministic mask workflow fixture."""
    yield from provision_canvas_with_mask(qapp, monkeypatch)


@pytest.fixture(scope="session", autouse=True)
def _redirect_mask_autosave_paths(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    """Keep mask autosave output inside the test session directory."""
    autosave_dir = tmp_path_factory.mktemp("mask-autosave")
    template = str(Path(autosave_dir) / "{image_name}-{mask_id}.png")
    defaults = config._EDITOR_DEFAULTS
    original_default = defaults["mask_autosave_path_template"]
    defaults["mask_autosave_path_template"] = template
    try:
        yield
    finally:
        defaults["mask_autosave_path_template"] = original_default
