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

"""Tests for the event-loop probe helper."""

from __future__ import annotations

from types import SimpleNamespace

from qpane.ui.event_probe import EventLoopProbe


class _Signal:
    """Minimal signal stub to support Qt-like connect semantics."""

    def __init__(self) -> None:
        self._callbacks: list[callable] = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)

    def emit(self) -> None:
        for callback in list(self._callbacks):
            callback()


class _TimerStub:
    """Timer stub capturing interval and start/stop calls."""

    def __init__(self) -> None:
        self.interval_ms = None
        self.timeout = _Signal()
        self.started = False
        self.stopped = False

    def setInterval(self, interval_ms: int) -> None:
        self.interval_ms = interval_ms

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def deleteLater(self) -> None:
        self.stopped = True


def test_probe_starts_only_once() -> None:
    """ensure_running should only create one timer instance."""
    created: list[_TimerStub] = []

    def _factory(_parent) -> _TimerStub:
        timer = _TimerStub()
        created.append(timer)
        return timer

    probe = EventLoopProbe(
        parent=SimpleNamespace(),
        threshold_getter=lambda: 10.0,
        timer_factory=_factory,
        clock=lambda: 0.0,
    )
    probe.ensure_running()
    probe.ensure_running()
    assert len(created) == 1
    assert created[0].started is True


def test_probe_emits_warning_on_lag() -> None:
    """Warnings should fire only when delta exceeds threshold."""
    times = iter([0.0, 0.020])
    warnings: list[tuple[float, float]] = []

    probe = EventLoopProbe(
        parent=SimpleNamespace(),
        threshold_getter=lambda: 10.0,
        warning_callback=lambda delta, threshold: warnings.append((delta, threshold)),
        timer_factory=lambda _parent: _TimerStub(),
        clock=lambda: next(times),
    )
    probe.ensure_running()
    probe._on_timeout()
    assert warnings
    delta_ms, threshold_ms = warnings[-1]
    assert delta_ms > threshold_ms


def test_probe_swallows_threshold_failures() -> None:
    """Failures in the threshold getter should disable warnings."""
    probe = EventLoopProbe(
        parent=SimpleNamespace(),
        threshold_getter=lambda: 1 / 0,
        warning_callback=lambda *_args: None,
        timer_factory=lambda _parent: _TimerStub(),
        clock=lambda: 0.0,
    )
    probe.ensure_running()
    probe._on_timeout()
    assert probe._safe_threshold() == 0.0
