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

"""Tests for QPaneState concurrency updates and propagation."""

from types import SimpleNamespace

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from qpane.concurrency import QThreadPoolExecutor, build_thread_policy
from qpane.core.config import Config
from qpane.core.state import QPaneState


class _DummyPool:
    def __init__(self) -> None:
        self.max_threads = 0

    def setMaxThreadCount(self, value: int) -> None:
        self.max_threads = int(value)

    def maxThreadCount(self) -> int:
        return int(self.max_threads)

    def start(self, *_args, **_kwargs) -> None:
        pass

    def waitForDone(self) -> None:
        pass


class _DummyQPane(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.interaction = SimpleNamespace(brush_size=30)
        self._masks_controller = SimpleNamespace(
            apply_config=lambda *_args, **_kwargs: None
        )

    def view(self):
        return None

    def catalog(self):
        return None


def test_apply_settings_pushes_concurrency_to_executor_live() -> None:
    if QApplication.instance() is None:
        QApplication([])
    config = Config()
    pool = _DummyPool()
    executor = QThreadPoolExecutor(
        policy=build_thread_policy(config), pool=pool, name="state-test"
    )
    qpane = _DummyQPane()
    state = QPaneState(
        qpane=qpane,
        initial_config=config,
        config_overrides=None,
        features=None,
        task_executor=executor,
        thread_policy=None,
        config_strict=False,
    )
    state.apply_settings(
        concurrency={"max_workers": 6, "category_limits": {"tiles": 3}}
    )
    snapshot = executor.snapshot()
    assert snapshot.max_workers == 6
    assert snapshot.category_limits.get("tiles") == 3
    assert pool.max_threads == 6


def test_executor_dirty_callback_wired_even_without_qpane_diagnostics() -> None:
    if QApplication.instance() is None:
        QApplication([])
    config = Config()
    pool = _DummyPool()
    executor = QThreadPoolExecutor(
        policy=build_thread_policy(config), pool=pool, name="state-test"
    )
    qpane = _DummyQPane()
    state = QPaneState(
        qpane=qpane,
        initial_config=config,
        config_overrides=None,
        features=None,
        task_executor=executor,
        thread_policy=None,
        config_strict=False,
    )
    # Trigger a dirty notification by mutating the executor policy.
    executor.setMaxWorkers(3)
    assert "executor" in state.diagnostics._dirty_domains
