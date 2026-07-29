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

"""Independent Qt fixtures for QPane's package test suite."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from PySide6.QtWidgets import QApplication

from tests.harness.process_lock import interactive_performance_isolation
from tests.harness.qt_lifetime import flush_deferred_qt_lifetime


@pytest.fixture(autouse=True)
def _isolate_interactive_performance(
    request: pytest.FixtureRequest,
) -> Iterator[None]:
    """Participate in suite-wide strict performance isolation."""
    with interactive_performance_isolation(request):
        yield


@pytest.fixture(scope="session")
def qapp() -> Iterator[QApplication]:
    """Provide one offscreen application for mounted viewer tests."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _flush_deferred_qt_deletions(qapp: QApplication) -> Iterator[None]:
    """Deliver deferred Qt deletions after each package test."""
    yield
    flush_deferred_qt_lifetime(qapp)
