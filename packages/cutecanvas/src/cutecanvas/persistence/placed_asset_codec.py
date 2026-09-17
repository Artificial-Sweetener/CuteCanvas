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
"""Own placed-image archive payloads, provenance, and legacy sample decoding."""

from __future__ import annotations

import uuid
import zipfile
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSize

from qpane.sdk.raster import numpy_to_qimage_argb32

from ..placed.model import (
    FileFingerprint,
    PlacedAssetMode,
    PlacedAssetSnapshot,
    PlacedAssetStatus,
)
from .image_payload_codec import image_manifest, read_image, write_image

_MAX_RASTER_PIXELS = 268_435_456
_MAX_COLOR_RASTER_BYTES = 1_073_741_824


def write_placed(
    container: zipfile.ZipFile, asset_id: uuid.UUID, snapshot: PlacedAssetSnapshot
) -> None:
    """Persist embedded samples or a linked asset's retained fallback."""
    if snapshot.image is None or (
        snapshot.mode is PlacedAssetMode.LINKED and not snapshot.keep_fallback
    ):
        return
    write_image(container, f"placed/{asset_id}.npy", snapshot.image)


def decode_placed(
    container: zipfile.ZipFile,
    asset_id: str,
    item: object,
) -> PlacedAssetSnapshot:
    """Validate and reconstruct one placed provenance payload."""
    if not isinstance(item, dict):
        raise TypeError("placed asset entries must be objects")
    size_values = item.get("source_size")
    if not isinstance(size_values, list) or len(size_values) != 2:
        raise ValueError("placed source_size must contain two integers")
    source_size = QSize(int(size_values[0]), int(size_values[1]))
    if source_size.isEmpty():
        raise ValueError("placed source_size must be positive")
    if source_size.width() * source_size.height() > _MAX_RASTER_PIXELS:
        raise ValueError("placed raster exceeds archive pixel limit")
    mode = PlacedAssetMode(str(item["mode"]))
    keep_fallback = bool(item["keep_fallback"])
    pixel_path = item.get("pixels")
    image = None
    if pixel_path is not None:
        expected_path = f"placed/{asset_id}.npy"
        if pixel_path != expected_path:
            raise ValueError("placed pixel path does not match its identifier")
        info = container.getinfo(expected_path)
        if info.file_size > _MAX_COLOR_RASTER_BYTES + 4096:
            raise ValueError("placed pixel payload exceeds archive size limit")
        encoding = item.get("image_encoding")
        if encoding is None:
            with container.open(expected_path) as stream:
                pixels = np.load(stream, allow_pickle=False)
            image = numpy_to_qimage_argb32(pixels)
        else:
            image = read_image(
                container,
                expected_path,
                source_size.width(),
                source_size.height(),
                encoding,
            )
        if image.size() != source_size:
            raise ValueError("placed pixels do not match source_size")
    if mode is PlacedAssetMode.EMBEDDED and image is None:
        raise ValueError("embedded placed assets require archived pixels")
    source_path_value = item.get("source_path")
    source_path = None if source_path_value is None else Path(str(source_path_value))
    fingerprint_values = item.get("fingerprint")
    fingerprint = None
    if fingerprint_values is not None:
        if not isinstance(fingerprint_values, list) or len(fingerprint_values) != 2:
            raise ValueError("placed fingerprint must contain size and modified time")
        fingerprint = FileFingerprint(
            int(fingerprint_values[0]),
            int(fingerprint_values[1]),
        )
    status = PlacedAssetStatus(str(item["status"]))
    error = None if item.get("error") is None else str(item["error"])
    if mode is PlacedAssetMode.LINKED and image is None:
        status = PlacedAssetStatus.MISSING
        error = "linked pixels were not embedded in the composition archive"
    return PlacedAssetSnapshot(
        image=image,
        source_size=source_size,
        mode=mode,
        source_path=source_path,
        status=status,
        error=error,
        keep_fallback=keep_fallback,
        fingerprint=fingerprint,
        content_revision=int(item["content_revision"]),
        generation=int(item["generation"]),
    )


def placed_manifest(
    asset_id: uuid.UUID,
    snapshot: PlacedAssetSnapshot,
) -> dict[str, object]:
    """Return provenance and optional fallback metadata for a placed source."""
    include_pixels = snapshot.image is not None and (
        snapshot.mode is PlacedAssetMode.EMBEDDED or snapshot.keep_fallback
    )
    fingerprint = (
        None
        if snapshot.fingerprint is None
        else [snapshot.fingerprint.size, snapshot.fingerprint.modified_ns]
    )
    return {
        "mode": snapshot.mode.value,
        "source_path": (
            None if snapshot.source_path is None else str(snapshot.source_path)
        ),
        "status": snapshot.status.value,
        "error": snapshot.error,
        "keep_fallback": snapshot.keep_fallback,
        "fingerprint": fingerprint,
        "content_revision": snapshot.content_revision,
        "generation": snapshot.generation,
        "source_size": [
            snapshot.source_size.width(),
            snapshot.source_size.height(),
        ],
        "pixels": f"placed/{asset_id}.npy" if include_pixels else None,
        "image_encoding": (
            image_manifest(snapshot.image)
            if include_pixels and snapshot.image is not None
            else None
        ),
    }
