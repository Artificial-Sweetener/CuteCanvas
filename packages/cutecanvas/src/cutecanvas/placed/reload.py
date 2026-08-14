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
"""Typed off-thread image decoding for linked placed assets."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QImage, QImageReader

from qpane.sdk.execution import CancellationToken

from .model import FileFingerprint

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PlacedAssetDecode:
    """Carry one detached linked-image decode result."""

    path: Path
    image: QImage | None
    fingerprint: FileFingerprint | None
    error_message: str | None
    missing: bool = False


def decode_placed_asset(
    path: Path,
    cancellation: CancellationToken,
) -> PlacedAssetDecode:
    """Decode and fingerprint one linked image cooperatively."""
    normalized_path = Path(path)
    cancellation.raise_if_cancelled()
    try:
        stat = normalized_path.stat()
    except FileNotFoundError:
        return PlacedAssetDecode(
            normalized_path,
            None,
            None,
            f"linked image does not exist: {normalized_path}",
            True,
        )
    fingerprint = FileFingerprint(stat.st_size, stat.st_mtime_ns)
    reader = QImageReader(str(normalized_path))
    reader.setAutoTransform(True)
    image = reader.read()
    cancellation.raise_if_cancelled()
    if image.isNull():
        return PlacedAssetDecode(
            normalized_path,
            None,
            None,
            reader.errorString() or "linked image could not be decoded",
        )
    return PlacedAssetDecode(
        normalized_path,
        QImage(image),
        fingerprint,
        None,
    )
