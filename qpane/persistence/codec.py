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
from PySide6.QtCore import QPointF, QRectF, QSize
from PySide6.QtGui import QColor

from ..catalog.source_reference import CatalogImageReference
from ..composition.layers import CompositionLayerInstance, instance_resources
from ..composition.model import (
    CompositionComparison,
    CompositionDocumentPolicy,
    CompositionOrigin,
    CompositionRecord,
)
from ..coverage import CoverageSnapshot
from ..masks.source_reference import MaskAssetReference
from ..placed.model import (
    FileFingerprint,
    PlacedAssetMode,
    PlacedAssetSnapshot,
    PlacedAssetStatus,
)
from ..placed.source_reference import PlacedAssetReference
from ..raster.color_surface import ColorRasterSnapshot
from ..raster.image_conversion import (
    numpy_to_qimage_argb32,
    qimage_to_numpy_argb32,
)
from ..raster.source_reference import EditableRasterReference
from ..raster.sparse_grid import (
    SparseRasterGrid,
    SparseRasterSnapshot,
    SparseRasterTile,
)
from ..scene.affine import LayerTransform
from ..scene.model import ClipCoordinateSpace, LayerClip, LayerInteractionPolicy
from ..scene.raster import RasterBounds, RasterExtentPolicy
from ..scene.source_references import LayerSourceReference
from ..types import ComparisonOrientation
from ..vector.effects import VectorMaskEffect
from ..vector.model import VectorDocument, VectorObject
from ..vector.public import (
    VectorFillRule,
    VectorObjectKind,
    VectorParagraphStyle,
    VectorPathCommand,
    VectorPathCommandKind,
    VectorShapeKind,
    VectorStrokeCap,
    VectorStrokeJoin,
    VectorStyle,
    VectorTextAlignment,
    VectorTextContent,
    VectorTextDirection,
    VectorTextSpan,
    VectorTextStyle,
)
from ..vector.source_reference import VectorDocumentReference
from .model import CompositionArchiveSnapshot

_FORMAT = "qpane-composition"
_VERSION = 8
_MIGRATABLE_VERSIONS = frozenset({2, 3, 4, 5, 6, 7, _VERSION})
_MAX_RASTER_PIXELS = 268_435_456
_MAX_COLOR_RASTER_BYTES = _MAX_RASTER_PIXELS * 4
_MAX_VECTOR_OBJECTS = 100_000
_MAX_VECTOR_POINTS = 4_000_000
_MAX_VECTOR_TEXT_CODEPOINTS = 4_000_000
_MAX_VECTOR_TEXT_SPANS = 100_000


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
                    self._write_sparse_tiles(container, "masks", mask_id, snapshot)
                for raster_id, snapshot in archive.rasters.items():
                    self._write_sparse_tiles(container, "rasters", raster_id, snapshot)
                for asset_id, snapshot in archive.placed_assets.items():
                    if snapshot.image is None or (
                        snapshot.mode is PlacedAssetMode.LINKED
                        and not snapshot.keep_fallback
                    ):
                        continue
                    with container.open(f"placed/{asset_id}.npy", "w") as stream:
                        np.save(
                            stream,
                            qimage_to_numpy_argb32(snapshot.image),
                            allow_pickle=False,
                        )
            os.replace(temporary_path, destination)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _write_sparse_tiles(
        container: zipfile.ZipFile,
        domain: str,
        resource_id: uuid.UUID,
        snapshot: SparseRasterSnapshot,
    ) -> None:
        """Write only allocated authoritative tiles for one sparse resource."""
        for index, tile in enumerate(snapshot.tiles):
            with container.open(f"{domain}/{resource_id}/{index}.npy", "w") as stream:
                np.save(stream, tile.pixels, allow_pickle=False)

    def read(self, path: Path) -> CompositionArchiveSnapshot:
        """Read and fully validate an archive before returning domain values."""
        with zipfile.ZipFile(Path(path), "r") as container:
            manifest = json.loads(container.read("manifest.json"))
            version = self._validate_header(manifest)
            snapshot = (
                self._read_version_two(container, manifest)
                if version == 2
                else self._read_resource_table(container, manifest, version=version)
            )
        self._validate_references(snapshot)
        return snapshot

    @staticmethod
    def _manifest(archive: CompositionArchiveSnapshot) -> dict[str, object]:
        """Return the JSON manifest for ``archive``."""
        return {
            "format": _FORMAT,
            "version": _VERSION,
            "document": CompositionArchiveCodec._encode_document(archive.document),
            "instances": [
                CompositionArchiveCodec._encode_layer(layer) for layer in archive.layers
            ],
            "resources": CompositionArchiveCodec._encode_resources(archive),
        }

    @staticmethod
    def _encode_document(document: CompositionRecord) -> dict[str, object]:
        """Encode composition-owned document values independently of resources."""
        bounds = document.canvas_bounds
        comparison = document.comparison
        return {
            "composition_id": str(document.composition_id),
            "origin": document.origin.value,
            "title": document.title,
            "canvas_bounds": [
                bounds.x(),
                bounds.y(),
                bounds.width(),
                bounds.height(),
            ],
            "navigation_image_id": (
                None
                if document.navigation_image_id is None
                else str(document.navigation_image_id)
            ),
            "comparison": (
                None
                if comparison is None
                else {
                    "source_id": str(comparison.source_id),
                    "source_path": (
                        None
                        if comparison.source_path is None
                        else str(comparison.source_path)
                    ),
                    "source_kind": comparison.source_kind,
                    "split_position": comparison.split_position,
                    "orientation": comparison.orientation.value,
                }
            ),
            "policy": {
                "removable": document.policy.removable,
                "comparison_enabled": document.policy.comparison_enabled,
                "remove_if_catalog_resource_missing": (
                    document.policy.remove_if_catalog_resource_missing
                ),
            },
        }

    @staticmethod
    def _encode_resources(
        archive: CompositionArchiveSnapshot,
    ) -> list[dict[str, object]]:
        """Return one deduplicated resource-table entry per referenced source."""
        resources: list[dict[str, object]] = []
        observed: set[tuple[str, uuid.UUID]] = set()
        for layer in archive.layers:
            for source in instance_resources(layer):
                key = (source.kind, source.resource_id)
                if key in observed:
                    continue
                observed.add(key)
                entry: dict[str, object] = {
                    "kind": source.kind,
                    "resource_id": str(source.resource_id),
                }
                if isinstance(source, MaskAssetReference):
                    snapshot = archive.masks[source.mask_id]
                    entry["payload"] = _coverage_manifest(source.mask_id, snapshot)
                elif isinstance(source, EditableRasterReference):
                    snapshot = archive.rasters[source.raster_id]
                    entry["payload"] = _raster_manifest(source.raster_id, snapshot)
                elif isinstance(source, PlacedAssetReference):
                    snapshot = archive.placed_assets[source.asset_id]
                    entry["payload"] = _placed_manifest(source.asset_id, snapshot)
                elif isinstance(source, VectorDocumentReference):
                    document = archive.vectors[source.vector_id]
                    entry["payload"] = _vector_manifest(document)
                resources.append(entry)
        return resources

    @staticmethod
    def _encode_layer(layer: CompositionLayerInstance) -> dict[str, object]:
        """Convert one immutable layer instance into JSON values."""
        transform = layer.transform
        tint = None if layer.tint is None else list(layer.tint.getRgb())
        return {
            "layer_id": str(layer.layer_id),
            "source": {
                "kind": layer.source.kind,
                "resource_id": str(layer.source.resource_id),
            },
            "transform": [
                transform.m11,
                transform.m12,
                transform.m21,
                transform.m22,
                transform.dx,
                transform.dy,
            ],
            "visible": layer.visible,
            "opacity": layer.opacity,
            "tint": tint,
            "hit_test": layer.hit_test,
            "interaction": [
                layer.interaction.selectable,
                layer.interaction.movable,
                layer.interaction.pixel_editable,
                layer.interaction.reorderable,
                layer.interaction.removable,
            ],
            "role": layer.role,
            "label": layer.label,
            "clip": _encode_clip(layer.clip),
            "metadata": dict(layer.metadata),
            "effects": [_encode_effect(effect) for effect in layer.effects],
        }

    @staticmethod
    def _decode_layer(
        item: object, *, legacy_version_two: bool = False
    ) -> CompositionLayerInstance:
        """Validate and reconstruct one layer manifest entry."""
        if not isinstance(item, dict):
            raise TypeError("layer entries must be objects")
        transform_values = item["transform"]
        interaction_values = item["interaction"]
        expected_transform_values = 4 if legacy_version_two else 6
        if (
            not isinstance(transform_values, list)
            or len(transform_values) != expected_transform_values
        ):
            raise ValueError(
                f"layer transform must contain {expected_transform_values} values"
            )
        if not isinstance(interaction_values, list) or len(interaction_values) not in {
            3,
            5,
        }:
            raise ValueError("layer interaction must contain three or five values")
        tint_values = item.get("tint")
        tint = None
        if tint_values is not None:
            if not isinstance(tint_values, list) or len(tint_values) != 4:
                raise ValueError("layer tint must contain four channels")
            tint = QColor(*(int(channel) for channel in tint_values))
        metadata = item.get("metadata", {})
        if not isinstance(metadata, dict):
            raise TypeError("layer metadata must be an object")
        source_item = (
            {
                "kind": item["source_kind"],
                "resource_id": item["source_id"],
            }
            if legacy_version_two
            else item.get("source")
        )
        if not isinstance(source_item, dict):
            raise TypeError("layer source must be an object")
        effects = item.get("effects", [])
        if not isinstance(effects, list):
            raise TypeError("layer effects must be a list")
        return CompositionLayerInstance(
            layer_id=uuid.UUID(item["layer_id"]),
            source=_decode_source_reference(
                str(source_item["kind"]), uuid.UUID(source_item["resource_id"])
            ),
            transform=(
                LayerTransform(
                    m11=float(transform_values[0]),
                    m22=float(transform_values[1]),
                    dx=float(transform_values[2]),
                    dy=float(transform_values[3]),
                )
                if legacy_version_two
                else LayerTransform(*(float(value) for value in transform_values))
            ),
            visible=bool(item["visible"]),
            opacity=float(item["opacity"]),
            tint=tint,
            hit_test=bool(item["hit_test"]),
            interaction=LayerInteractionPolicy(
                selectable=bool(interaction_values[0]),
                movable=bool(interaction_values[1]),
                pixel_editable=bool(interaction_values[2]),
                reorderable=(
                    bool(interaction_values[3])
                    if len(interaction_values) == 5
                    else False
                ),
                removable=(
                    bool(interaction_values[4])
                    if len(interaction_values) == 5
                    else False
                ),
            ),
            role=str(item["role"]),
            label=None if item.get("label") is None else str(item["label"]),
            clip=_decode_clip(item.get("clip")),
            metadata=dict(metadata),
            effects=tuple(_decode_effect(effect) for effect in effects),
        )

    @classmethod
    def _read_version_two(
        cls,
        container: zipfile.ZipFile,
        manifest: dict[str, object],
    ) -> CompositionArchiveSnapshot:
        """Migrate one validated flat version-2 manifest into current values."""
        image_id = uuid.UUID(str(manifest["image_id"]))
        layer_items = manifest["layers"]
        mask_items = manifest["masks"]
        raster_items = manifest.get("rasters", {})
        assert isinstance(layer_items, list)
        assert isinstance(mask_items, dict)
        assert isinstance(raster_items, dict)
        layers = tuple(
            cls._decode_layer(item, legacy_version_two=True) for item in layer_items
        )
        masks = {
            uuid.UUID(mask_id): cls._decode_mask(container, mask_id, item)
            for mask_id, item in mask_items.items()
        }
        rasters = {
            uuid.UUID(raster_id): cls._decode_raster(container, raster_id, item)
            for raster_id, item in raster_items.items()
        }
        return CompositionArchiveSnapshot(
            cls._legacy_document(image_id, image_id, layers, masks, rasters, {}),
            layers,
            masks,
            rasters,
            {},
            {},
        )

    @classmethod
    def _read_resource_table(
        cls,
        container: zipfile.ZipFile,
        manifest: dict[str, object],
        *,
        version: int,
    ) -> CompositionArchiveSnapshot:
        """Decode one validated current resource-table manifest."""
        instance_items = manifest["instances"]
        resource_items = manifest["resources"]
        assert isinstance(instance_items, list)
        assert isinstance(resource_items, list)
        layers = tuple(cls._decode_layer(item) for item in instance_items)
        masks: dict[uuid.UUID, SparseRasterSnapshot] = {}
        rasters: dict[uuid.UUID, SparseRasterSnapshot] = {}
        placed_assets: dict[uuid.UUID, PlacedAssetSnapshot] = {}
        vectors: dict[uuid.UUID, VectorDocument] = {}
        resource_keys: set[tuple[str, uuid.UUID]] = set()
        for item in resource_items:
            if not isinstance(item, dict):
                raise TypeError("resource entries must be objects")
            kind = str(item["kind"])
            resource_id = uuid.UUID(str(item["resource_id"]))
            key = (kind, resource_id)
            if key in resource_keys:
                raise ValueError("archive resource identities must be unique")
            resource_keys.add(key)
            source = _decode_source_reference(kind, resource_id)
            payload = item.get("payload")
            if isinstance(source, MaskAssetReference):
                masks[resource_id] = cls._decode_mask(
                    container, str(resource_id), payload
                )
            elif isinstance(source, EditableRasterReference):
                rasters[resource_id] = cls._decode_raster(
                    container, str(resource_id), payload
                )
            elif isinstance(source, PlacedAssetReference):
                placed_assets[resource_id] = cls._decode_placed(
                    container,
                    str(resource_id),
                    payload,
                )
            elif isinstance(source, VectorDocumentReference):
                vectors[resource_id] = cls._decode_vector(resource_id, payload)
            elif payload is not None:
                raise ValueError("catalog resources must not contain payloads")
        referenced_keys = {
            (layer.source.kind, layer.source.resource_id) for layer in layers
        }
        if referenced_keys != resource_keys:
            raise ValueError("archive instances and resource table must match")
        document = (
            cls._decode_document(manifest.get("document"))
            if version >= 8
            else cls._legacy_document(
                uuid.UUID(str(manifest["composition_id"])),
                uuid.UUID(str(manifest["base_image_id"])),
                layers,
                masks,
                rasters,
                vectors,
            )
        )
        return CompositionArchiveSnapshot(
            document,
            layers,
            masks,
            rasters,
            placed_assets,
            vectors,
        )

    @staticmethod
    def _decode_document(item: object) -> CompositionRecord:
        """Validate and decode one current composition document payload."""
        if not isinstance(item, dict):
            raise TypeError("archive document must be an object")
        bounds_values = item.get("canvas_bounds")
        if not isinstance(bounds_values, list) or len(bounds_values) != 4:
            raise ValueError("document canvas_bounds must contain four values")
        comparison_item = item.get("comparison")
        comparison = None
        if comparison_item is not None:
            if not isinstance(comparison_item, dict):
                raise TypeError("document comparison must be an object or null")
            source_path = comparison_item.get("source_path")
            comparison = CompositionComparison(
                source_id=uuid.UUID(str(comparison_item["source_id"])),
                source_path=None if source_path is None else Path(str(source_path)),
                source_kind=str(comparison_item["source_kind"]),
                split_position=float(comparison_item["split_position"]),
                orientation=ComparisonOrientation(str(comparison_item["orientation"])),
            )
        policy_item = item.get("policy")
        if not isinstance(policy_item, dict):
            raise TypeError("document policy must be an object")
        navigation_id = item.get("navigation_image_id")
        return CompositionRecord(
            composition_id=uuid.UUID(str(item["composition_id"])),
            origin=CompositionOrigin(str(item["origin"])),
            title=str(item["title"]),
            canvas_bounds=QRectF(*(float(value) for value in bounds_values)),
            navigation_image_id=(
                None if navigation_id is None else uuid.UUID(str(navigation_id))
            ),
            comparison=comparison,
            policy=CompositionDocumentPolicy(
                removable=bool(policy_item["removable"]),
                comparison_enabled=bool(policy_item["comparison_enabled"]),
                remove_if_catalog_resource_missing=bool(
                    policy_item["remove_if_catalog_resource_missing"]
                ),
            ),
        )

    @staticmethod
    def _legacy_document(
        composition_id: uuid.UUID,
        base_image_id: uuid.UUID,
        layers: tuple[CompositionLayerInstance, ...],
        masks: dict[uuid.UUID, SparseRasterSnapshot],
        rasters: dict[uuid.UUID, SparseRasterSnapshot],
        vectors: dict[uuid.UUID, VectorDocument],
    ) -> CompositionRecord:
        """Migrate a pre-document archive into one explicit document value."""
        placements = []
        for layer in layers:
            bounds = None
            if isinstance(layer.source, MaskAssetReference):
                snapshot = masks.get(layer.source.mask_id)
                bounds = None if snapshot is None else snapshot.bounds
            elif isinstance(layer.source, EditableRasterReference):
                snapshot = rasters.get(layer.source.raster_id)
                bounds = None if snapshot is None else snapshot.bounds
            elif isinstance(layer.source, VectorDocumentReference):
                document = vectors.get(layer.source.vector_id)
                bounds = None if document is None else document.bounds
            if bounds is not None:
                placements.append(layer.transform.map_bounds(bounds))
        if placements:
            left = min(placement.x for placement in placements)
            top = min(placement.y for placement in placements)
            right = max(placement.x + placement.width for placement in placements)
            bottom = max(placement.y + placement.height for placement in placements)
            canvas = QRectF(left, top, max(1.0, right - left), max(1.0, bottom - top))
        else:
            canvas = QRectF(0.0, 0.0, 1.0, 1.0)
        return CompositionRecord(
            composition_id=composition_id,
            origin=CompositionOrigin.DEFAULT_IMAGE,
            title="Migrated composition",
            canvas_bounds=canvas,
            navigation_image_id=base_image_id,
        )

    @staticmethod
    def _decode_vector(vector_id: uuid.UUID, item: object) -> VectorDocument:
        """Validate and reconstruct one semantic vector document payload."""
        if not isinstance(item, dict):
            raise TypeError("vector document entries must be objects")
        bounds_values = item.get("bounds")
        object_values = item.get("objects")
        if not isinstance(bounds_values, list) or len(bounds_values) != 4:
            raise ValueError("vector bounds must contain four integers")
        if not isinstance(object_values, list):
            raise TypeError("vector objects must be a list")
        if len(object_values) > _MAX_VECTOR_OBJECTS:
            raise ValueError("vector document exceeds archive object limit")
        objects: list[VectorObject] = []
        point_count = 0
        for value in object_values:
            vector_object, object_points = _decode_vector_object(value)
            point_count += object_points
            if point_count > _MAX_VECTOR_POINTS:
                raise ValueError("vector document exceeds archive point limit")
            objects.append(vector_object)
        return VectorDocument(
            vector_id=vector_id,
            bounds=RasterBounds(*(int(value) for value in bounds_values)),
            objects=tuple(objects),
            revision=int(item.get("revision", 0)),
        )

    @staticmethod
    def _decode_placed(
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
            with container.open(expected_path) as stream:
                pixels = np.load(stream, allow_pickle=False)
            image = numpy_to_qimage_argb32(pixels)
            if image.size() != source_size:
                raise ValueError("placed pixels do not match source_size")
        if mode is PlacedAssetMode.EMBEDDED and image is None:
            raise ValueError("embedded placed assets require archived pixels")
        source_path_value = item.get("source_path")
        source_path = (
            None if source_path_value is None else Path(str(source_path_value))
        )
        fingerprint_values = item.get("fingerprint")
        fingerprint = None
        if fingerprint_values is not None:
            if not isinstance(fingerprint_values, list) or len(fingerprint_values) != 2:
                raise ValueError(
                    "placed fingerprint must contain size and modified time"
                )
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

    @staticmethod
    def _decode_mask(
        container: zipfile.ZipFile,
        mask_id: str,
        item: object,
    ) -> SparseRasterSnapshot:
        """Validate and reconstruct one mask surface entry."""
        if not isinstance(item, dict):
            raise TypeError("mask entries must be objects")
        if item.get("storage") == "sparse-tiles":
            return CompositionArchiveCodec._decode_sparse_tiles(
                container,
                "masks",
                mask_id,
                item,
                channels=1,
                byte_limit=_MAX_RASTER_PIXELS,
            )
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
        snapshot = CoverageSnapshot(
            bounds=bounds,
            extent_policy=RasterExtentPolicy(item["extent_policy"]),
            pixels=pixels,
        )
        return _sparse_from_dense(
            snapshot.bounds,
            snapshot.extent_policy,
            snapshot.pixels,
            channels=1,
        )

    @staticmethod
    def _decode_raster(
        container: zipfile.ZipFile,
        raster_id: str,
        item: object,
    ) -> SparseRasterSnapshot:
        """Validate and reconstruct one editable color raster payload."""
        if not isinstance(item, dict):
            raise TypeError("raster entries must be objects")
        if item.get("storage") == "sparse-tiles":
            return CompositionArchiveCodec._decode_sparse_tiles(
                container,
                "rasters",
                raster_id,
                item,
                channels=4,
                byte_limit=_MAX_COLOR_RASTER_BYTES,
            )
        bounds_values = item["bounds"]
        if not isinstance(bounds_values, list) or len(bounds_values) != 4:
            raise ValueError("raster bounds must contain four integers")
        bounds = RasterBounds(*(int(value) for value in bounds_values))
        if bounds.width * bounds.height > _MAX_RASTER_PIXELS:
            raise ValueError("color raster exceeds archive pixel limit")
        expected_path = f"rasters/{raster_id}.npy"
        if item["pixels"] != expected_path:
            raise ValueError("raster pixel path does not match its identifier")
        info = container.getinfo(expected_path)
        if info.file_size > _MAX_COLOR_RASTER_BYTES + 4096:
            raise ValueError("color raster payload exceeds archive size limit")
        with container.open(expected_path) as stream:
            pixels = np.load(stream, allow_pickle=False)
        snapshot = ColorRasterSnapshot(
            bounds=bounds,
            extent_policy=RasterExtentPolicy(item["extent_policy"]),
            pixels=pixels,
        )
        return _sparse_from_dense(
            snapshot.bounds,
            snapshot.extent_policy,
            snapshot.pixels,
            channels=4,
        )

    @staticmethod
    def _decode_sparse_tiles(
        container: zipfile.ZipFile,
        domain: str,
        resource_id: str,
        item: dict[str, object],
        *,
        channels: int,
        byte_limit: int,
    ) -> SparseRasterSnapshot:
        """Validate and reconstruct allocated tiles without reading their envelope."""
        bounds_values = item.get("bounds")
        if not isinstance(bounds_values, list) or len(bounds_values) != 4:
            raise ValueError("sparse raster bounds must contain four integers")
        bounds = RasterBounds(*(int(value) for value in bounds_values))
        tile_size = int(item.get("tile_size", 0))
        if tile_size < 16 or tile_size > 4096:
            raise ValueError("sparse raster tile_size is invalid")
        if int(item.get("channels", 0)) != channels:
            raise ValueError("sparse raster channel count is invalid")
        tile_items = item.get("tiles")
        if not isinstance(tile_items, list):
            raise TypeError("sparse raster tiles must be a list")
        maximum_tiles = max(1, byte_limit // (tile_size * tile_size * channels))
        if len(tile_items) > maximum_tiles:
            raise ValueError("sparse raster exceeds archive tile limit")
        tiles: list[SparseRasterTile] = []
        retained_bytes = 0
        observed_bounds: set[RasterBounds] = set()
        for index, tile_item in enumerate(tile_items):
            if not isinstance(tile_item, dict):
                raise TypeError("sparse raster tile entries must be objects")
            tile_bounds_values = tile_item.get("bounds")
            if not isinstance(tile_bounds_values, list) or len(tile_bounds_values) != 4:
                raise ValueError("sparse tile bounds must contain four integers")
            tile_bounds = RasterBounds(*(int(value) for value in tile_bounds_values))
            if (
                tile_bounds.width != tile_size
                or tile_bounds.height != tile_size
                or tile_bounds.x % tile_size
                or tile_bounds.y % tile_size
                or tile_bounds in observed_bounds
            ):
                raise ValueError("sparse tile geometry is invalid or duplicated")
            expected_path = f"{domain}/{resource_id}/{index}.npy"
            if tile_item.get("pixels") != expected_path:
                raise ValueError("sparse tile path does not match its index")
            info = container.getinfo(expected_path)
            retained_bytes += info.file_size
            if retained_bytes > byte_limit + len(tile_items) * 4096:
                raise ValueError("sparse raster payload exceeds archive size limit")
            with container.open(expected_path) as stream:
                pixels = np.load(stream, allow_pickle=False)
            tiles.append(SparseRasterTile(tile_bounds, pixels))
            observed_bounds.add(tile_bounds)
        return SparseRasterSnapshot(
            bounds,
            RasterExtentPolicy(str(item["extent_policy"])),
            channels,
            tile_size,
            tuple(tiles),
        )

    @staticmethod
    def _validate_header(manifest: object) -> int:
        """Reject unknown formats, versions, or malformed root collections."""
        if not isinstance(manifest, dict):
            raise TypeError("archive manifest must be an object")
        if manifest.get("format") != _FORMAT:
            raise ValueError("unsupported composition archive format")
        version = manifest.get("version")
        if version not in _MIGRATABLE_VERSIONS:
            raise ValueError("unsupported composition archive version")
        if version == 2:
            if not isinstance(manifest.get("layers"), list):
                raise TypeError("archive layers must be a list")
            if not isinstance(manifest.get("masks"), dict):
                raise TypeError("archive masks must be an object")
            if not isinstance(manifest.get("rasters", {}), dict):
                raise TypeError("archive rasters must be an object")
        else:
            if not isinstance(manifest.get("instances"), list):
                raise TypeError("archive instances must be a list")
            if not isinstance(manifest.get("resources"), list):
                raise TypeError("archive resources must be a list")
            if version >= 8 and not isinstance(manifest.get("document"), dict):
                raise TypeError("archive document must be an object")
        return int(version)

    @staticmethod
    def _validate_references(archive: CompositionArchiveSnapshot) -> None:
        """Require one base image and exact mask payload references."""
        mask_ids = {
            layer.source.mask_id
            for layer in archive.layers
            if isinstance(layer.source, MaskAssetReference)
        }
        if mask_ids != set(archive.masks):
            raise ValueError("archive mask sources and payloads must match")
        raster_ids = {
            layer.source.raster_id
            for layer in archive.layers
            if isinstance(layer.source, EditableRasterReference)
        }
        if raster_ids != set(archive.rasters):
            raise ValueError("archive raster sources and payloads must match")
        placed_ids = {
            layer.source.asset_id
            for layer in archive.layers
            if isinstance(layer.source, PlacedAssetReference)
        }
        if placed_ids != set(archive.placed_assets):
            raise ValueError("archive placed sources and payloads must match")
        vector_ids = {
            source.vector_id
            for layer in archive.layers
            for source in instance_resources(layer)
            if isinstance(source, VectorDocumentReference)
        }
        if vector_ids != set(archive.vectors):
            raise ValueError("archive vector sources and payloads must match")


def _decode_source_reference(kind: str, resource_id: uuid.UUID) -> LayerSourceReference:
    """Decode one version-2 source reference through known domain values."""
    constructors = {
        "catalog-image": CatalogImageReference,
        "mask": MaskAssetReference,
        "raster": EditableRasterReference,
        "placed-asset": PlacedAssetReference,
        "vector": VectorDocumentReference,
    }
    constructor = constructors.get(kind)
    if constructor is None:
        raise ValueError(f"unsupported layer source kind: {kind}")
    return constructor(resource_id)


def _coverage_manifest(
    mask_id: uuid.UUID, snapshot: SparseRasterSnapshot
) -> dict[str, object]:
    """Return one mask resource payload manifest."""
    if snapshot.bounds is None:
        raise ValueError("archived mask resources require non-null bounds")
    return {
        "bounds": [
            snapshot.bounds.x,
            snapshot.bounds.y,
            snapshot.bounds.width,
            snapshot.bounds.height,
        ],
        "extent_policy": snapshot.extent_policy.value,
        "storage": "sparse-tiles",
        "channels": snapshot.channels,
        "tile_size": snapshot.tile_size,
        "tiles": [
            {
                "bounds": [
                    tile.bounds.x,
                    tile.bounds.y,
                    tile.bounds.width,
                    tile.bounds.height,
                ],
                "pixels": f"masks/{mask_id}/{index}.npy",
            }
            for index, tile in enumerate(snapshot.tiles)
        ],
    }


def _raster_manifest(
    raster_id: uuid.UUID, snapshot: SparseRasterSnapshot
) -> dict[str, object]:
    """Return one editable-raster resource payload manifest."""
    return {
        "bounds": [
            snapshot.bounds.x,
            snapshot.bounds.y,
            snapshot.bounds.width,
            snapshot.bounds.height,
        ],
        "extent_policy": snapshot.extent_policy.value,
        "storage": "sparse-tiles",
        "channels": snapshot.channels,
        "tile_size": snapshot.tile_size,
        "tiles": [
            {
                "bounds": [
                    tile.bounds.x,
                    tile.bounds.y,
                    tile.bounds.width,
                    tile.bounds.height,
                ],
                "pixels": f"rasters/{raster_id}/{index}.npy",
            }
            for index, tile in enumerate(snapshot.tiles)
        ],
    }


def _sparse_from_dense(
    bounds: RasterBounds | None,
    extent_policy: RasterExtentPolicy,
    pixels: np.ndarray,
    *,
    channels: int,
) -> SparseRasterSnapshot:
    """Migrate one legacy dense payload into current sparse authority."""
    grid = SparseRasterGrid(channels=channels, tile_size=512)
    if bounds is not None:
        grid.replace(bounds, pixels)
    return grid.snapshot(bounds, extent_policy)


def _placed_manifest(
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
    }


def _vector_manifest(document: VectorDocument) -> dict[str, object]:
    """Return serializable semantic geometry for one vector document."""
    return {
        "bounds": [
            document.bounds.x,
            document.bounds.y,
            document.bounds.width,
            document.bounds.height,
        ],
        "revision": document.revision,
        "objects": [_vector_object_manifest(item) for item in document.objects],
    }


def _vector_object_manifest(item: VectorObject) -> dict[str, object]:
    """Return one stable vector object's serializable semantic values."""
    transform = item.transform
    style = item.style
    return {
        "object_id": str(item.object_id),
        "kind": item.kind.value,
        "bounds": list(item.local_bounds),
        "transform": [
            transform.m11,
            transform.m12,
            transform.m21,
            transform.m22,
            transform.dx,
            transform.dy,
        ],
        "style": {
            "fill": _encode_color(style.fill),
            "stroke": _encode_color(style.stroke),
            "stroke_width": style.stroke_width,
            "opacity": style.opacity,
            "join": style.join.value,
            "cap": style.cap.value,
            "dash_pattern": list(style.dash_pattern),
            "fill_rule": style.fill_rule.value,
        },
        "shape_kind": None if item.shape_kind is None else item.shape_kind.value,
        "path": [
            {
                "kind": command.kind.value,
                "points": [[point.x(), point.y()] for point in command.points],
            }
            for command in item.path
        ],
        "text": None if item.text is None else _vector_text_manifest(item.text),
    }


def _vector_text_manifest(content: VectorTextContent) -> dict[str, object]:
    """Return serializable Unicode, character, and paragraph semantics."""
    return {
        "value": content.text,
        "style": _vector_text_style_manifest(content.style),
        "spans": [
            {
                "start": span.start,
                "length": span.length,
                "style": _vector_text_style_manifest(span.style),
            }
            for span in content.spans
        ],
        "paragraph": {
            "alignment": content.paragraph.alignment.value,
            "direction": content.paragraph.direction.value,
            "line_height": content.paragraph.line_height,
        },
    }


def _vector_text_style_manifest(style: VectorTextStyle) -> dict[str, object]:
    """Return serializable semantic font request values."""
    return {
        "families": list(style.families),
        "font_size": style.font_size,
        "weight": style.weight,
        "italic": style.italic,
        "letter_spacing": style.letter_spacing,
        "color": _encode_color(style.color),
    }


def _decode_vector_object(item: object) -> tuple[VectorObject, int]:
    """Validate one serialized vector object and return its point count."""
    if not isinstance(item, dict):
        raise TypeError("vector object entries must be objects")
    bounds_values = item.get("bounds")
    transform_values = item.get("transform")
    style_values = item.get("style")
    path_values = item.get("path", [])
    if not isinstance(bounds_values, list) or len(bounds_values) != 4:
        raise ValueError("vector object bounds must contain four values")
    if not isinstance(transform_values, list) or len(transform_values) != 6:
        raise ValueError("vector object transform must contain six values")
    if not isinstance(style_values, dict):
        raise TypeError("vector object style must be an object")
    if not isinstance(path_values, list):
        raise TypeError("vector object path must be a list")
    commands: list[VectorPathCommand] = []
    point_count = 0
    for command_value in path_values:
        if not isinstance(command_value, dict):
            raise TypeError("vector path commands must be objects")
        points_value = command_value.get("points", [])
        if not isinstance(points_value, list):
            raise TypeError("vector command points must be a list")
        points = []
        for point_value in points_value:
            if not isinstance(point_value, list) or len(point_value) != 2:
                raise ValueError("vector points must contain two values")
            points.append(QPointF(float(point_value[0]), float(point_value[1])))
        point_count += len(points)
        commands.append(
            VectorPathCommand(
                VectorPathCommandKind(str(command_value["kind"])),
                tuple(points),
            )
        )
    style = VectorStyle(
        fill=_decode_color(style_values.get("fill")),
        stroke=_decode_color(style_values.get("stroke")),
        stroke_width=float(style_values["stroke_width"]),
        opacity=float(style_values["opacity"]),
        join=VectorStrokeJoin(str(style_values["join"])),
        cap=VectorStrokeCap(str(style_values["cap"])),
        dash_pattern=tuple(float(value) for value in style_values["dash_pattern"]),
        fill_rule=VectorFillRule(str(style_values["fill_rule"])),
    )
    shape_value = item.get("shape_kind")
    text = _decode_vector_text(item.get("text"))
    return (
        VectorObject(
            object_id=uuid.UUID(str(item["object_id"])),
            kind=VectorObjectKind(str(item["kind"])),
            local_bounds=tuple(float(value) for value in bounds_values),
            transform=LayerTransform(*(float(value) for value in transform_values)),
            style=style,
            shape_kind=(
                None if shape_value is None else VectorShapeKind(str(shape_value))
            ),
            path=tuple(commands),
            text=text,
        ),
        point_count,
    )


def _decode_vector_text(item: object) -> VectorTextContent | None:
    """Validate and decode one optional semantic text payload."""
    if item is None:
        return None
    if not isinstance(item, dict):
        raise TypeError("vector text must be an object or null")
    value = item.get("value")
    spans_value = item.get("spans")
    paragraph_value = item.get("paragraph")
    if not isinstance(value, str):
        raise TypeError("vector text value must be a string")
    if len(value) > _MAX_VECTOR_TEXT_CODEPOINTS:
        raise ValueError("vector text exceeds archive character limit")
    if not isinstance(spans_value, list):
        raise TypeError("vector text spans must be a list")
    if len(spans_value) > _MAX_VECTOR_TEXT_SPANS:
        raise ValueError("vector text exceeds archive span limit")
    if not isinstance(paragraph_value, dict):
        raise TypeError("vector text paragraph must be an object")
    spans: list[VectorTextSpan] = []
    for span_value in spans_value:
        if not isinstance(span_value, dict):
            raise TypeError("vector text spans must be objects")
        spans.append(
            VectorTextSpan(
                int(span_value["start"]),
                int(span_value["length"]),
                _decode_vector_text_style(span_value.get("style")),
            )
        )
    return VectorTextContent(
        value,
        _decode_vector_text_style(item.get("style")),
        tuple(spans),
        VectorParagraphStyle(
            VectorTextAlignment(str(paragraph_value["alignment"])),
            VectorTextDirection(str(paragraph_value["direction"])),
            float(paragraph_value["line_height"]),
        ),
    )


def _decode_vector_text_style(item: object) -> VectorTextStyle:
    """Validate and decode one semantic font request."""
    if not isinstance(item, dict):
        raise TypeError("vector text style must be an object")
    families = item.get("families")
    if not isinstance(families, list) or any(
        not isinstance(family, str) for family in families
    ):
        raise TypeError("vector text families must be a list of strings")
    color = _decode_color(item.get("color"))
    if color is None:
        raise ValueError("vector text color must not be null")
    return VectorTextStyle(
        tuple(families),
        float(item["font_size"]),
        int(item["weight"]),
        bool(item["italic"]),
        float(item["letter_spacing"]),
        color,
    )


def _encode_color(color: QColor | None) -> list[int] | None:
    """Return detached RGBA channels for one optional semantic color."""
    return None if color is None else list(color.getRgb())


def _decode_color(item: object) -> QColor | None:
    """Validate and decode one optional RGBA color value."""
    if item is None:
        return None
    if not isinstance(item, list) or len(item) != 4:
        raise ValueError("vector colors must contain four channels")
    channels = tuple(int(value) for value in item)
    if any(value < 0 or value > 255 for value in channels):
        raise ValueError("vector color channels must be between 0 and 255")
    return QColor(*channels)


def _encode_clip(clip: LayerClip | None) -> dict[str, object] | None:
    """Return detached JSON values for one optional instance clip."""
    if clip is None:
        return None
    return {
        "coordinate_space": clip.coordinate_space.value,
        "rect": [clip.x, clip.y, clip.width, clip.height],
    }


def _decode_clip(item: object) -> LayerClip | None:
    """Validate and decode one optional instance clip."""
    if item is None:
        return None
    if not isinstance(item, dict):
        raise TypeError("layer clip must be an object")
    rect = item.get("rect")
    if not isinstance(rect, list) or len(rect) != 4:
        raise ValueError("layer clip rect must contain four values")
    return LayerClip(
        coordinate_space=ClipCoordinateSpace(str(item["coordinate_space"])),
        x=float(rect[0]),
        y=float(rect[1]),
        width=float(rect[2]),
        height=float(rect[3]),
    )


def _encode_effect(effect: object) -> dict[str, object]:
    """Encode one known typed composition layer effect."""
    if not isinstance(effect, VectorMaskEffect):
        raise TypeError(f"unsupported layer effect: {type(effect)!r}")
    transform = effect.transform
    return {
        "kind": effect.kind,
        "source": {
            "kind": effect.source.kind,
            "resource_id": str(effect.source.resource_id),
        },
        "transform": [
            transform.m11,
            transform.m12,
            transform.m21,
            transform.m22,
            transform.dx,
            transform.dy,
        ],
        "object_ids": [str(object_id) for object_id in effect.object_ids],
        "inverted": effect.inverted,
    }


def _decode_effect(item: object) -> VectorMaskEffect:
    """Validate and decode one known typed composition layer effect."""
    if not isinstance(item, dict):
        raise TypeError("layer effects must be objects")
    if item.get("kind") != "vector-mask":
        raise ValueError(f"unsupported layer effect kind: {item.get('kind')}")
    source = item.get("source")
    transform = item.get("transform")
    object_ids = item.get("object_ids", [])
    if not isinstance(source, dict) or source.get("kind") != "vector":
        raise ValueError("vector masks require a vector source")
    if not isinstance(transform, list) or len(transform) != 6:
        raise ValueError("vector mask transforms must contain six values")
    if not isinstance(object_ids, list):
        raise TypeError("vector mask object IDs must be a list")
    return VectorMaskEffect(
        VectorDocumentReference(uuid.UUID(str(source["resource_id"]))),
        LayerTransform(*(float(value) for value in transform)),
        tuple(uuid.UUID(str(value)) for value in object_ids),
        bool(item.get("inverted", False)),
    )
