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
"""Immutable provenance and snapshots for placed raster assets."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage


class PlacedAssetMode(str, Enum):
    """Persistence relationship between a placed source and external storage."""

    EMBEDDED = "embedded"
    LINKED = "linked"


class PlacedAssetStatus(str, Enum):
    """Current availability of a placed source's latest requested content."""

    READY = "ready"
    LOADING = "loading"
    MISSING = "missing"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class FileFingerprint:
    """Identify one observed external file version without using path as identity."""

    size: int
    modified_ns: int


@dataclass(frozen=True, slots=True)
class PlacedAssetSnapshot:
    """Capture one placed source including its last valid display fallback."""

    image: QImage | None
    source_size: QSize
    mode: PlacedAssetMode
    source_path: Path | None
    status: PlacedAssetStatus
    error: str | None
    keep_fallback: bool
    fingerprint: FileFingerprint | None
    content_revision: int
    generation: int

    def __post_init__(self) -> None:
        """Detach mutable image storage and validate revisions."""
        image = None if self.image is None else QImage(self.image)
        object.__setattr__(self, "image", image)
        object.__setattr__(self, "source_size", QSize(self.source_size))
        if self.source_size.isEmpty():
            raise ValueError("placed assets require positive source dimensions")
        if image is not None and (image.isNull() or image.size() != self.source_size):
            raise ValueError("placed fallback pixels must match source dimensions")
        if self.mode is PlacedAssetMode.EMBEDDED and image is None:
            raise ValueError("embedded placed assets require pixels")
        if self.mode is PlacedAssetMode.EMBEDDED and self.source_path is not None:
            raise ValueError("embedded placed assets cannot retain a source path")
        if self.content_revision < 0 or self.generation < 0:
            raise ValueError("placed asset revisions must be non-negative")
