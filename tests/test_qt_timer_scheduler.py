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

import threading
import time
from collections.abc import Callable

from qpane.concurrency import QtTimerScheduler


def test_qt_timer_scheduler_cancels_dispatched_timer_before_start(qapp) -> None:
    fired = []
    dispatched: list[Callable[[], None]] = []
    scheduler = QtTimerScheduler(qapp, dispatcher=lambda cb: dispatched.append(cb))
    handle_box: dict[str, object] = {}

    def _schedule_off_thread() -> None:
        handle_box["handle"] = scheduler.schedule("k", 5, lambda: fired.append("fired"))

    worker = threading.Thread(target=_schedule_off_thread)
    worker.start()
    worker.join()
    handle = handle_box.get("handle")
    assert handle is not None
    scheduler.cancel(handle)
    assert dispatched, "dispatcher should have been used for off-thread scheduling"
    for callback in dispatched:
        callback()
    qapp.processEvents()
    assert not fired, "cancel before dispatch should prevent timer start"


def test_qt_timer_scheduler_falls_back_when_dispatcher_missing(qapp) -> None:
    fired = []
    scheduler = QtTimerScheduler(qapp)
    handle_box: dict[str, object] = {}

    def _schedule_off_thread() -> None:
        handle_box["handle"] = scheduler.schedule("k", 5, lambda: fired.append("fired"))

    worker = threading.Thread(target=_schedule_off_thread)
    worker.start()
    worker.join()
    for _ in range(40):
        if fired:
            break
        qapp.processEvents()
        time.sleep(0.01)
    assert fired == ["fired"], "fallback singleShot should still fire on main thread"


def test_qt_timer_scheduler_cancel_fallback_without_dispatcher(qapp) -> None:
    fired = []
    scheduler = QtTimerScheduler(qapp)
    handle_box: dict[str, object] = {}

    def _schedule_off_thread() -> None:
        handle_box["handle"] = scheduler.schedule(
            "k", 20, lambda: fired.append("fired")
        )

    worker = threading.Thread(target=_schedule_off_thread)
    worker.start()
    worker.join()
    handle = handle_box.get("handle")
    assert handle is not None
    cancel_thread = threading.Thread(target=lambda: scheduler.cancel(handle))
    cancel_thread.start()
    cancel_thread.join()
    start = time.monotonic()
    while time.monotonic() - start < 0.5:
        qapp.processEvents()
        time.sleep(0.01)
    assert not fired, "fallback cancel should stop timer created via singleShot"
