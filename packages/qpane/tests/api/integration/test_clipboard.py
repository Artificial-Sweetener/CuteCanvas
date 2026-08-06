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

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPixmap
from qpane.ui import copyToClipboard


def test_copy_to_clipboard_success(qapp):
    pixmap = QPixmap(2, 2)
    pixmap.fill(Qt.white)
    clipboard = QGuiApplication.clipboard()
    clipboard.clear()
    assert copyToClipboard(pixmap) is True
    stored = clipboard.pixmap()
    assert not stored.isNull()
    assert stored.size() == pixmap.size()


def test_copy_to_clipboard_null_pixmap_returns_false(qapp):
    clipboard = QGuiApplication.clipboard()
    baseline = QPixmap(1, 1)
    baseline.fill(Qt.black)
    assert copyToClipboard(baseline) is True
    baseline_key = clipboard.pixmap().cacheKey()
    null_pixmap = QPixmap()
    assert copyToClipboard(null_pixmap) is False
    assert clipboard.pixmap().cacheKey() == baseline_key


def test_copy_to_clipboard_requires_qapp(monkeypatch, qapp):
    monkeypatch.setattr(QGuiApplication, "instance", lambda: None)
    pixmap = QPixmap(1, 1)
    pixmap.fill(Qt.white)
    with pytest.raises(RuntimeError):
        copyToClipboard(pixmap)
