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

"""Build and persist detached mask autosave products."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage, Qt
from qpane.sdk.execution import CancellationToken

MaskImagePayload = QImage | bytes | Callable[[], QImage]


def encode_blank_mask(
    size: tuple[int, int],
    cancellation: CancellationToken,
) -> bytes:
    """Encode one transparent mask image after validating its dimensions."""
    cancellation.raise_if_cancelled()
    width, height = (max(0, int(size[0])), max(0, int(size[1])))
    if width <= 0 or height <= 0:
        raise ValueError("blank mask dimensions must be positive")
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    return _encode_png(image, cancellation)


def save_mask_payload(
    payload: MaskImagePayload,
    path: Path,
    cancellation: CancellationToken,
) -> Path:
    """Encode and atomically replace one mask file."""
    cancellation.raise_if_cancelled()
    resolved = payload() if callable(payload) else payload
    image_bytes = (
        resolved if isinstance(resolved, bytes) else _encode_png(resolved, cancellation)
    )
    cancellation.raise_if_cancelled()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(image_bytes)
            temporary.flush()
        cancellation.raise_if_cancelled()
        os.replace(temporary_path, target)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return target


def _encode_png(image: QImage, cancellation: CancellationToken) -> bytes:
    """Return PNG bytes for one non-null image."""
    cancellation.raise_if_cancelled()
    if image.isNull():
        raise RuntimeError("Mask projection returned a null image")
    buffer = QBuffer()
    try:
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
            raise RuntimeError("QBuffer failed to open for writing")
        if not image.save(buffer, "PNG"):
            raise RuntimeError("QImage.save returned False while encoding mask")
        return bytes(buffer.data())
    finally:
        if buffer.isOpen():
            buffer.close()


__all__ = [
    "MaskImagePayload",
    "encode_blank_mask",
    "save_mask_payload",
]
