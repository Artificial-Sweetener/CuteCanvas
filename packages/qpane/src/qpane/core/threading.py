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

"""Qt threading utilities shared across QPane managers."""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QObject, QThread


def assert_qt_main_thread(owner: QObject, *, cache_attr: str = "_main_thread") -> None:
    """Raise AssertionError when ``owner`` is mutated off Qt's main thread."""
    app = QCoreApplication.instance()
    if app is None:
        return
    cached_thread = getattr(owner, cache_attr, None)
    if cached_thread is None:
        cached_thread = app.thread() if hasattr(app, "thread") else None
        setattr(owner, cache_attr, cached_thread)
    if cached_thread is None:
        return
    assert (
        QThread.currentThread() == cached_thread
    ), f"{type(owner).__name__} state mutated off main thread"
