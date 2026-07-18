#    QPane - High-performance PySide6 image viewer
#    Copyright (C) 2025  Artificial Sweetener and contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

"""Versioned, validated, and atomic private composition archive I/O."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
import zipfile
from pathlib import Path

import numpy as np
from PySide6.QtGui import QColor

from ..composition.layers import CompositionLayerInstance, CompositionLayerSourceKind
from ..masks.surface import MaskSurfaceSnapshot
from ..scene.model import LayerInteractionPolicy
from ..scene.raster import LayerTransform, RasterBounds, RasterExtentPolicy
from .model import CompositionArchiveSnapshot

_FORMAT = "qpane-composition"
_VERSION = 1
_MAX_RASTER_PIXELS = 268_435_456


class CompositionArchiveCodec:
    """Encode and decode one private QPane composition archive version."""

    def write(self, archive: CompositionArchiveSnapshot, path: Path) -> None:
        """Atomically write ``archive`` to ``path`` as a ZIP container."""
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=f".{destination.name}.",
                suffix=".tmp",
                dir=destination.parent,
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
            with zipfile.ZipFile(
                temporary_path,
                "w",
                compression=zipfile.ZIP_DEFLATED,
            ) as container:
                container.writestr(
                    "manifest.json",
                    json.dumps(self._manifest(archive), separators=(",", ":")),
                )
                for mask_id, snapshot in archive.masks.items():
                    with container.open(f"masks/{mask_id}.npy", "w") as stream:
                        np.save(stream, snapshot.pixels, allow_pickle=False)
            os.replace(temporary_path, destination)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def read(self, path: Path) -> CompositionArchiveSnapshot:
        """Read and fully validate an archive before returning domain values."""
        with zipfile.ZipFile(Path(path), "r") as container:
            manifest = json.loads(container.read("manifest.json"))
            self._validate_header(manifest)
            image_id = uuid.UUID(manifest["image_id"])
            layers = tuple(self._decode_layer(item) for item in manifest["layers"])
            masks = {
                uuid.UUID(mask_id): self._decode_mask(container, mask_id, item)
                for mask_id, item in manifest["masks"].items()
            }
        snapshot = CompositionArchiveSnapshot(image_id, layers, masks)
        self._validate_references(snapshot)
        return snapshot

    @staticmethod
    def _manifest(archive: CompositionArchiveSnapshot) -> dict[str, object]:
        """Return the JSON manifest for ``archive``."""
        return {
            "format": _FORMAT,
            "version": _VERSION,
            "image_id": str(archive.image_id),
            "layers": [
                CompositionArchiveCodec._encode_layer(layer) for layer in archive.layers
            ],
            "masks": {
                str(mask_id): {
                    "bounds": [
                        snapshot.bounds.x,
                        snapshot.bounds.y,
                        snapshot.bounds.width,
                        snapshot.bounds.height,
                    ],
                    "extent_policy": snapshot.extent_policy.value,
                    "pixels": f"masks/{mask_id}.npy",
                }
                for mask_id, snapshot in archive.masks.items()
                if snapshot.bounds is not None
            },
        }

    @staticmethod
    def _encode_layer(layer: CompositionLayerInstance) -> dict[str, object]:
        """Convert one immutable layer instance into JSON values."""
        transform = layer.transform
        tint = None if layer.tint is None else list(layer.tint.getRgb())
        return {
            "layer_id": str(layer.layer_id),
            "source_kind": layer.source_kind.value,
            "source_id": str(layer.source_id),
            "transform": [
                transform.scale_x,
                transform.scale_y,
                transform.translate_x,
                transform.translate_y,
            ],
            "visible": layer.visible,
            "opacity": layer.opacity,
            "tint": tint,
            "hit_test": layer.hit_test,
            "interaction": [
                layer.interaction.selectable,
                layer.interaction.movable,
            ],
            "role": layer.role,
            "label": layer.label,
        }

    @staticmethod
    def _decode_layer(item: object) -> CompositionLayerInstance:
        """Validate and reconstruct one layer manifest entry."""
        if not isinstance(item, dict):
            raise TypeError("layer entries must be objects")
        transform_values = item["transform"]
        interaction_values = item["interaction"]
        if not isinstance(transform_values, list) or len(transform_values) != 4:
            raise ValueError("layer transform must contain four values")
        if not isinstance(interaction_values, list) or len(interaction_values) != 2:
            raise ValueError("layer interaction must contain two values")
        tint_values = item.get("tint")
        tint = None
        if tint_values is not None:
            if not isinstance(tint_values, list) or len(tint_values) != 4:
                raise ValueError("layer tint must contain four channels")
            tint = QColor(*(int(channel) for channel in tint_values))
        return CompositionLayerInstance(
            layer_id=uuid.UUID(item["layer_id"]),
            source_kind=CompositionLayerSourceKind(item["source_kind"]),
            source_id=uuid.UUID(item["source_id"]),
            transform=LayerTransform(*(float(value) for value in transform_values)),
            visible=bool(item["visible"]),
            opacity=float(item["opacity"]),
            tint=tint,
            hit_test=bool(item["hit_test"]),
            interaction=LayerInteractionPolicy(
                selectable=bool(interaction_values[0]),
                movable=bool(interaction_values[1]),
            ),
            role=str(item["role"]),
            label=None if item.get("label") is None else str(item["label"]),
        )

    @staticmethod
    def _decode_mask(
        container: zipfile.ZipFile,
        mask_id: str,
        item: object,
    ) -> MaskSurfaceSnapshot:
        """Validate and reconstruct one mask surface entry."""
        if not isinstance(item, dict):
            raise TypeError("mask entries must be objects")
        bounds_values = item["bounds"]
        if not isinstance(bounds_values, list) or len(bounds_values) != 4:
            raise ValueError("mask bounds must contain four integers")
        bounds = RasterBounds(*(int(value) for value in bounds_values))
        if bounds.width * bounds.height > _MAX_RASTER_PIXELS:
            raise ValueError("mask surface exceeds archive pixel limit")
        pixel_path = item["pixels"]
        expected_path = f"masks/{mask_id}.npy"
        if pixel_path != expected_path:
            raise ValueError("mask pixel path does not match its identifier")
        info = container.getinfo(expected_path)
        if info.file_size > _MAX_RASTER_PIXELS + 4096:
            raise ValueError("mask pixel payload exceeds archive size limit")
        with container.open(expected_path) as stream:
            pixels = np.load(stream, allow_pickle=False)
        return MaskSurfaceSnapshot(
            bounds=bounds,
            extent_policy=RasterExtentPolicy(item["extent_policy"]),
            pixels=pixels,
        )

    @staticmethod
    def _validate_header(manifest: object) -> None:
        """Reject unknown formats, versions, or malformed root collections."""
        if not isinstance(manifest, dict):
            raise TypeError("archive manifest must be an object")
        if manifest.get("format") != _FORMAT:
            raise ValueError("unsupported composition archive format")
        if manifest.get("version") != _VERSION:
            raise ValueError("unsupported composition archive version")
        if not isinstance(manifest.get("layers"), list):
            raise TypeError("archive layers must be a list")
        if not isinstance(manifest.get("masks"), dict):
            raise TypeError("archive masks must be an object")

    @staticmethod
    def _validate_references(archive: CompositionArchiveSnapshot) -> None:
        """Require one base image and exact mask payload references."""
        mask_ids = {
            layer.source_id
            for layer in archive.layers
            if layer.source_kind is CompositionLayerSourceKind.MASK
        }
        if mask_ids != set(archive.masks):
            raise ValueError("archive mask sources and payloads must match")
        base_count = sum(
            layer.source_kind is CompositionLayerSourceKind.CATALOG_IMAGE
            and layer.source_id == archive.image_id
            for layer in archive.layers
        )
        if base_count != 1:
            raise ValueError("archive requires exactly one matching base image")
