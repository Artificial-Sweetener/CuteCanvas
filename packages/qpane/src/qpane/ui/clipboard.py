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

"""Clipboard helpers for QPane's Qt facade."""

from PySide6.QtGui import QGuiApplication, QPixmap


def copyToClipboard(pixmap: QPixmap) -> bool:
    """Copy `pixmap` into the system clipboard.

    Args:
        pixmap: Image payload to publish; skipped when the pixmap is null.

    Returns:
        True when the pixmap is written, False when the call leaves the clipboard untouched.

    Raises:
        RuntimeError: If no QGuiApplication instance is running.

    Side effects:
        Replaces the clipboard's current pixmap contents.
    """
    app = QGuiApplication.instance()
    if app is None:
        raise RuntimeError(
            "copyToClipboard requires an active QGuiApplication; ensure a GUI application is running before calling."
        )
    if pixmap is None or pixmap.isNull():
        return False
    clipboard = app.clipboard()
    clipboard.setPixmap(pixmap)
    return True
