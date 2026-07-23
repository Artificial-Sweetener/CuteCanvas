#    CuteCanvas - High-performance layered image editor
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

"""Teach background image loading without blocking the editor window."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal, Slot
from PySide6.QtGui import QImage, QImageReader


class ImageLoaderSignals(QObject):
    """Signals emitted by the ImageLoaderWorker during processing.

    Must be a QObject subclass because QRunnable is not.
    """

    image_loaded = Signal(Path, QImage)
    finished = Signal(int)  # Emits count of loaded images


class ImageLoaderWorker(QRunnable):
    """Background worker that loads a batch of images from disk.

    Iterates through the provided paths, loads them using QImageReader,
    and emits them one by one. This allows the UI to update progressively.
    """

    def __init__(self, paths: Iterable[Path]) -> None:
        """Initialize the worker with a batch of images.

        Args:
            paths: A list of file paths to be loaded in the background.
        """
        super().__init__()
        self.paths = list(paths)
        self.signals = ImageLoaderSignals()

    @Slot()
    def run(self) -> None:
        """Execute the loading loop on a background thread."""
        count = 0
        for path in self.paths:
            reader = QImageReader(str(path))
            reader.setAutoTransform(True)
            image = reader.read()
            if not image.isNull():
                self.signals.image_loaded.emit(path, image)
                count += 1
        self.signals.finished.emit(count)
