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

"""Prove that a standalone QPane owns its execution-runtime lifetime."""

from __future__ import annotations

from PySide6.QtGui import QColor, QImage

from qpane import QPane
from qpane_test_support.qt_lifetime import flush_deferred_qt_lifetime


def test_destroyed_standalone_qpane_joins_every_owned_worker(qapp) -> None:
    """Widget destruction must leave no worker active at process teardown."""
    pane = QPane()
    runtime = pane._execution_runtime
    workers = tuple(
        thread
        for backend in runtime._backends
        for thread in (
            *getattr(backend, "_threads", ()),
            getattr(getattr(backend, "_diagnostics", None), "_thread", None),
        )
        if thread is not None
    )
    image = QImage(4096, 3072, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(24, 72, 120, 255))
    pane.resize(800, 600)
    pane.setImage(image)
    pane.show()
    qapp.processEvents()

    pane.close()
    pane.deleteLater()
    del pane
    flush_deferred_qt_lifetime(qapp)

    assert runtime.is_closed
    assert workers
    assert not any(thread.is_alive() for thread in workers)
