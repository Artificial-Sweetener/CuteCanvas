#    QPane + CuteCanvas - High-performance PySide6 rendering and editing
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

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from cutecanvas import CuteCanvas
from cutecanvas.core import config
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from qpane import QPane

from tests.harness.process_lock import InterprocessPerformanceIsolation


@pytest.fixture(autouse=True)
def _isolate_interactive_performance(request: pytest.FixtureRequest) -> Iterator[None]:
    """Give strict latency probes exclusive access to shared hardware."""
    worker_input = getattr(request.config, "workerinput", None)
    if worker_input is None:
        worker_slot = 0
        worker_count = 1
    else:
        worker_id = str(worker_input["workerid"])
        worker_slot = int(worker_id.removeprefix("gw"))
        worker_count = int(worker_input["workercount"])
    exclusive = request.node.get_closest_marker("interactive_performance") is not None
    with InterprocessPerformanceIsolation(
        Path.cwd() / ".pytest-tmp",
        worker_slot=worker_slot,
        worker_count=worker_count,
        exclusive=exclusive,
    ):
        yield


@pytest.fixture(scope="session")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _flush_deferred_qt_deletions(qapp: QApplication) -> Iterator[None]:
    """Deliver deferred QObject deletions on the GUI thread after every test."""
    yield
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


@pytest.fixture()
def qpane_core(qapp: QApplication) -> Iterator[QPane]:
    """Provision a bare QPane viewer and ensure it is cleaned up."""
    qpane = QPane()
    try:
        yield qpane
    finally:
        qpane.deleteLater()


@pytest.fixture()
def canvas_core(qapp: QApplication) -> Iterator[CuteCanvas]:
    """Provision a bare CuteCanvas editor and ensure it is cleaned up."""
    canvas = CuteCanvas(features=())
    try:
        yield canvas
    finally:
        canvas.deleteLater()


@pytest.fixture()
def qpane_view(qpane_core: QPane):
    """Expose the view collaborator for rendering-focused tests."""
    return qpane_core.view()


@pytest.fixture()
def qpane_presenter(qpane_view):
    """Return the RenderingPresenter owned by the shared view."""
    return qpane_view.presenter


@pytest.fixture()
def qpane_viewport(qpane_view):
    """Provide the view-managed viewport for convenience in tests."""
    return qpane_view.viewport


@pytest.fixture()
def qpane_renderer(qpane_view):
    """Provide the view-managed renderer for rendering tests."""
    return qpane_view.renderer


@pytest.fixture()
def catalog(qpane_core: QPane):
    """Expose the Catalog attached to the shared qpane."""
    return qpane_core.catalog()


@pytest.fixture()
def mask_workflow(canvas_core: CuteCanvas):
    """Expose the Masks workflow to encourage workflow-centric tests."""
    return canvas_core._masks_controller


@pytest.fixture()
def mask_service(mask_workflow):
    """Return the attached MaskService when mask tooling is installed."""
    service = mask_workflow.mask_service()
    return service


@pytest.fixture(scope="session", autouse=True)
def _redirect_mask_autosave_paths(tmp_path_factory):
    """Keep mask autosave outputs inside a temporary directory during tests."""
    autosave_dir = tmp_path_factory.mktemp("mask-autosave")
    template = str(Path(autosave_dir) / "{image_name}-{mask_id}.png")
    defaults = config._EDITOR_DEFAULTS
    original_default = defaults["mask_autosave_path_template"]
    defaults["mask_autosave_path_template"] = template
    try:
        yield
    finally:
        defaults["mask_autosave_path_template"] = original_default
