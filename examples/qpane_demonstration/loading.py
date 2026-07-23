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
"""Background image decoding for the QPane viewer example."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, Signal
from PySide6.QtGui import QImageReader


class ImageLoadSignals(QObject):
    """Publish detached image-decoding results to the GUI thread."""

    loaded = Signal(object, object, object)
    failed = Signal(object, str)
    finished = Signal()


class ImageLoader(QRunnable):
    """Decode a batch of potentially large images outside the GUI thread."""

    def __init__(self, paths: tuple[Path, ...]) -> None:
        """Retain normalized paths for one asynchronous load batch."""
        super().__init__()
        self.paths = tuple(Path(path) for path in paths)
        self.signals = ImageLoadSignals()

    def run(self) -> None:
        """Decode each path and prepare its small catalog preview."""
        try:
            for path in self.paths:
                reader = QImageReader(str(path))
                reader.setAutoTransform(True)
                image = reader.read()
                if image.isNull():
                    self.signals.failed.emit(path, reader.errorString())
                    continue
                thumbnail = image.scaled(
                    144,
                    96,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.signals.loaded.emit(path, image, thumbnail)
        finally:
            self.signals.finished.emit()
